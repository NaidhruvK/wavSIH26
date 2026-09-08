"""8 Sep, "break it deliberately": what S3 does with input that is not a signal.

The day-clock row is six adversarial inputs - pure noise, DC, clipped, two
overlapping signals, empty band, wrong sample rate - and the definition of done
is "every case returns a status, never an exception". The verify line is "six
adversarial files, six clean statuses".

WHY THIS RUNS THE BLIND SEARCH AND NOT ONLY THE PLUG-INS
--------------------------------------------------------
`tests/unit/test_s3_receive.py` has covered most of this set since 4 Sep, but it
covers it through `MODULATIONS[name].receive(iq, params)` - a NAMED plug-in
handed a symbol rate. `receive_best(iq, params_from_s2(s2, fs))` is the entry
point an orchestrator is meant to use: a ranked search over every plug-in, a
rate rescue, a de-duplication grid and a deadline, none of which the plug-in
path exercises. All of that landed on 7 Sep (`e7b9649`) and none of it had ever
been shown an adversarial input.

CORRECTION, 8 Sep, found by running the six files through the real CLI: an
earlier draft of this file said `receive_best` is "the path the service takes".
**IT IS NOT.** `service/orchestrator.py:856` calls
`MODULATIONS[chosen_scheme].receive(...)` - one named plug-in - and
`chosen_scheme` is `qpsk` on every corpus file measured. See section 10 of the
report; it is the largest finding of the day and it is not S3's to fix. Both
paths are still measured here, and the plug-in table in section 5 is now the
one that describes production behaviour.

The rate rescue is the specific thing worth pointing at. When every candidate is
refused for absence, `lockcheck.strongest_line` reads the peak off the spectrum
and proposes it as a symbol rate. On a signal that is present that recovers 28
files; on noise it is, by construction, a rate generator.
`reports/s3_rate_rescue.md` measured it in isolation (0/384 noise draws
accepted) - this measures it in place, inside the search, which is where it can
actually do damage. So every case runs BOTH paths and both are reported.

"ADVERSARIAL" IS TWO DIFFERENT QUESTIONS, AND CONFLATING THEM WAS A BUG
-----------------------------------------------------------------------
The first draft of this study scored `ok` on ANY adversarial case as a false
positive. That is wrong, and the measurements said so immediately: a hard-
clipped QPSK capture comes back `ok`/qpsk, and it is RIGHT to. QPSK is
constant-modulus, so clipping at a quarter of peak removes the RRC pulse
shaping's overshoot and almost nothing else - peak-to-average goes 1.72 -> 1.02
and the symbols survive. A receiver that refused it would be worse, not safer.

The set splits:

  ABSENCE   pure noise, DC only, empty band, all zeros, single impulse.
            There is no signal. `ok` is a confident lie and must never happen.
            This is S3's half of the gate item - the same question Nehal's
            column asks of S4 as "uncoded random data must not produce a false
            code detection".

  DEGRADED  clipped, two overlapping signals, wrong sample rate.
            A signal IS present and is damaged, contended or mislabelled. `ok`
            is permitted when the answer is correct, and the test is whether
            the content is right - scored with the repo's own `measured_ber`
            against the bits that were actually transmitted, not with a
            hand-rolled comparison.

Scoring both classes by the same rule would have called the clipped row a
defect and hidden the only real finding in the set (§4 of the report).

WHY EVERY CASE RUNS OVER MANY SEEDS
-----------------------------------
The first draft of this probe drew all its cases from ONE shared RNG stream, in
dict order. Re-running it after adding a case shifted the draws, and "empty
band" moved from `low_confidence`/2fsk to `failed`/no-modulation between two
runs of what looked like the same experiment. Neither verdict was wrong; the
single draw was never a measurement. Each case now owns a seeded generator and
is drawn SEEDS times, and the table reports the distribution.

THE KNOWN-ANSWER CELL IS IN THE TABLE, AS ALWAYS
------------------------------------------------
`control: clean qpsk` is a 20 dB QPSK capture with the right sample rate. Its
answer is known: `ok`, modulation qpsk, measured BER ~0, on every seed. It is
the first row of every table on purpose, and it has already earned its place
once today - see `_sig`, where it caught a hand-rolled transmitter that made
three of the six cases incapable of measuring anything.

Runtime ~5 min. `--render-only` re-renders the markdown from the CSV.
`--write-files` writes the six .wav files described in the report.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
import traceback
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.s2_estimate import estimate                      # noqa: E402
from pipeline.s3_receive.search import (params_from_s2,        # noqa: E402
                                        receive_best)
from registry import MODULATIONS                               # noqa: E402
from tests.fixtures import corpus                              # noqa: E402
from tests.fixtures.corpus import synth                        # noqa: E402

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "s3_adversarial.csv"
MD_PATH = HERE / "s3_adversarial.md"
FILE_DIR = HERE / "s3_adversarial"

FS = 200_000.0
RS = 50_000.0
N = 120_000
N_BITS = 60_000
SEEDS = 8

# The statuses S3 is allowed to return. Anything else is a contract break, and
# an exception is not on the list at all.
VALID = ("ok", "low_confidence", "failed", "out_of_envelope")


def _seed(case: str, seed: int) -> int:
    """A stable per-case seed.

    `hash("pure noise")` is salted per process (PYTHONHASHSEED), so seeding off
    it would give this study a different corpus on every run and make the six
    committed .wav files unreproducible from this script. crc32 is stable
    across processes, versions and machines.
    """
    return zlib.crc32(case.encode()) % (2 ** 31) + seed


# --- the inputs --------------------------------------------------------------
#
# Every generator takes an integer seed and returns (iq, declared_fs, ref_bits).
# `declared_fs` is separate from the content on purpose: "wrong sample rate" is
# the case where those two disagree, which is exactly what the service's
# `fs_hint` form field lets a caller do. `ref_bits` is None when the case has
# no transmitted stream to be right about.

def _sig(seed: int, scheme: str = "qpsk", snr_db: float = 20.0,
         sps: int = 4, n_bits: int = N_BITS):
    """A real capture, from the repo's ONE modulator, with its reference bits.

    The first version of this study hand-rolled a QPSK transmitter here -
    rectangular pulses, its own noise - and the control cell caught it
    immediately: a clean 20 dB capture came back `low_confidence`/2fsk on 8 of
    8 seeds, and 0 of 8 `ok`. The receiver was right and the generator was
    wrong; S3's matched filter is RRC and a rectangular NRZ stream is not the
    signal it exists to receive.

    That matters beyond the control row. `clipped`, `two overlapping` and
    `wrong sample rate` were all built ON that generator, so all three were
    clipping / summing / mislabelling a signal S3 already refused - three cases
    that could only ever have reported a refusal, whatever the receiver did.
    A study that cannot distinguish its own inputs from noise is §10's
    "measured something other than what its title said", and the known-answer
    cell is what caught it again.

    `tests/fixtures/corpus.synth` is a thin call into `zoo.rf.through_channel`.
    Its docstring records that `tests/fixtures/rf_channel.py` was DELETED on
    4 Sep so there would be exactly one modulator in the repo; writing a second
    one here was undoing that without noticing.
    """
    bits = np.random.default_rng(seed).integers(0, 2, n_bits).astype(np.uint8)
    iq, _fs, _rs, n_used = synth(scheme, n_bits=n_bits, snr_db=snr_db,
                                 sps=sps, seed=seed, bits=bits)
    return iq, bits[:n_used]


def _control(seed):
    iq, ref = _sig(seed)
    return iq, FS, ref


def _pure_noise(seed):
    rng = np.random.default_rng(seed)
    return rng.normal(0, 1, N) + 1j * rng.normal(0, 1, N), FS, None


def _dc_only(seed):
    # A carrier and nothing else. No symbol transitions exist to time to.
    return np.full(N, 1.0 + 0j), FS, None


def _empty_band(seed):
    # A band with no emitter in it: thermal noise 120 dB down. Distinct from
    # `pure noise` in amplitude alone, which is the point - it asks whether any
    # decision in the chain is made on an ABSOLUTE level rather than a ratio.
    rng = np.random.default_rng(seed)
    return 1e-6 * (rng.normal(0, 1, N) + 1j * rng.normal(0, 1, N)), FS, None


def _clipped(seed):
    # A real capture driven hard into saturation, which is what an overdriven
    # front end produces - not a synthetic square wave.
    x, ref = _sig(seed)
    lim = 0.25 * float(np.max(np.abs(x)))
    mag = np.abs(x)
    return x * np.where(mag > lim, lim / np.maximum(mag, 1e-30), 1.0), FS, ref


def _two_overlapping(seed):
    # Two independent emitters in one band at equal power and DIFFERENT symbol
    # rates (sps 4 -> 50 kHz, sps 5 -> 40 kHz), so neither is a sub-harmonic of
    # the other. The frequency shift is applied to the second capture rather
    # than asked of the modulator: a second emitter elsewhere in the band is a
    # channel fact, not a property of its transmitter.
    #
    # ref_bits is the FIRST emitter's stream. It is a reference in the weak
    # sense only - "did it recover emitter A" - and recovering neither is an
    # equally correct answer here, so the report scores this row on refusal and
    # quotes the BER rather than asserting on it.
    a, ref = _sig(seed, sps=4)
    b, _ = _sig(seed + 5000, sps=5)
    n = min(a.size, b.size)
    a, b = a[:n], b[:n]
    b = b * np.exp(2j * np.pi * 30_000.0 * np.arange(n) / FS)
    b = b * np.sqrt(float(np.mean(np.abs(a) ** 2))
                    / max(float(np.mean(np.abs(b) ** 2)), 1e-30))
    return a + b, FS, ref


def _wrong_sample_rate(seed):
    # A perfectly good 200 kHz capture whose header says 48 kHz. Nothing about
    # the samples is adversarial; the METADATA is. This is the one case a judge
    # can produce without touching the signal at all, and the service hands
    # `fs_hint` straight through from a form field.
    iq, ref = _sig(seed)
    return iq, 48_000.0, ref


def _all_zeros(seed):
    return np.zeros(N, dtype=complex), FS, None


def _single_impulse(seed):
    x = np.zeros(N, dtype=complex)
    x[0] = 1.0
    return x, FS, None


# Order matters: the control is first so it is read first.
CASES = {
    "control: clean qpsk": _control,
    "pure noise": _pure_noise,
    "DC only": _dc_only,
    "empty band": _empty_band,
    "clipped (saturated)": _clipped,
    "two overlapping signals": _two_overlapping,
    "wrong sample rate": _wrong_sample_rate,
    "all zeros": _all_zeros,
    "single impulse": _single_impulse,
}

# The six the day-clock row names, in its order.
THE_SIX = ("pure noise", "DC only", "clipped (saturated)",
           "two overlapping signals", "empty band", "wrong sample rate")

# No signal is present: `ok` is a false positive and must never happen.
ABSENCE = ("pure noise", "DC only", "empty band", "all zeros", "single impulse")
# A signal is present and damaged/contended/mislabelled: `ok` is allowed when
# the answer is right.
DEGRADED = ("clipped (saturated)", "two overlapping signals",
            "wrong sample rate")


# --- measurement -------------------------------------------------------------

def _blind(iq, declared_fs, ref_bits):
    """The service path: real S2, then the ranked search. Never raises."""
    t0 = time.perf_counter()
    try:
        s2 = estimate(iq, declared_fs)
        res = receive_best(iq, params_from_s2(s2, declared_fs))
    except Exception as exc:                                   # noqa: BLE001
        return {"raised": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=4).replace("\n", " | "),
                "status": "", "modulation": "", "chain_runs": "", "n_llrs": "",
                "finite": "", "rate_used": "", "ber": "", "reason": "",
                "secs": time.perf_counter() - t0}
    v = res.values or {}
    llrs = None if res.llrs is None else np.asarray(res.llrs)
    ber = ""
    if ref_bits is not None and llrs is not None and llrs.size:
        # The repo's own scorer, which already handles the phase-rotation
        # ambiguity and the acquisition offset. §10: a hand-rolled BER
        # comparison here produced a table of 60 coin flips once already.
        try:
            ber = float(corpus.measured_ber(res, np.asarray(ref_bits)))
        except Exception:                                      # noqa: BLE001
            ber = ""
    return {
        "raised": "", "trace": "",
        "status": res.status,
        "modulation": v.get("modulation", "") or "",
        "chain_runs": v.get("search_chain_runs", ""),
        "n_llrs": 0 if llrs is None else int(llrs.size),
        "finite": "" if llrs is None else bool(np.all(np.isfinite(llrs))),
        "rate_used": v.get("symbol_rate_used", ""),
        "ber": ber,
        "reason": " ".join(str(res.reason or "").split()),
        "secs": time.perf_counter() - t0,
    }


def _plugin(iq, declared_fs, name):
    """The named-plug-in path, with a plausible rate. Never raises."""
    params = {"fs": declared_fs, "symbol_rate": declared_fs / 4.0}
    t0 = time.perf_counter()
    try:
        res = MODULATIONS[name].receive(iq, params)
        out = np.asarray(MODULATIONS[name].demodulate(iq, params))
    except Exception as exc:                                   # noqa: BLE001
        return {"raised": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=4).replace("\n", " | "),
                "status": "", "finite": "", "secs": time.perf_counter() - t0}
    return {
        "raised": "", "trace": "",
        "status": res.status,
        "finite": bool(out.dtype == np.float64 and np.all(np.isfinite(out))),
        "secs": time.perf_counter() - t0,
    }


def measure() -> list[dict]:
    rows: list[dict] = []
    total = len(CASES) * SEEDS
    done = 0
    for case, gen in CASES.items():
        for seed in range(SEEDS):
            iq, declared_fs, ref = gen(_seed(case, seed))
            iq = np.asarray(iq, dtype=complex)

            b = _blind(iq, declared_fs, ref)
            rows.append({"case": case, "seed": seed, "path": "blind search",
                         "plugin": "", "declared_fs": declared_fs, **b})
            for name in MODULATIONS:
                p = _plugin(iq, declared_fs, name)
                rows.append({"case": case, "seed": seed, "path": "plug-in",
                             "plugin": name, "declared_fs": declared_fs,
                             "modulation": name, "chain_runs": "", "n_llrs": "",
                             "rate_used": "", "ber": "", "reason": "", **p})
            done += 1
            print(f"  [{done:3d}/{total}] {case:26s} seed {seed}  "
                  f"blind -> {b['raised'] or b['status']:15s} "
                  f"{b['modulation']}", flush=True)
    return rows


FIELDS = ["case", "seed", "path", "plugin", "declared_fs", "raised", "status",
          "modulation", "chain_runs", "n_llrs", "finite", "rate_used", "ber",
          "reason", "secs", "trace"]


def write_csv(rows):
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read_csv():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --- the six files -----------------------------------------------------------

def write_files():
    """Six .wav files in the corpus's own format, for the verify line.

    Stereo (I, Q) at the DECLARED sample rate, matching `zoo/rf.write_wav_pair`
    so they ingest through S0 exactly like a corpus file. Seed 0 of each case,
    so every committed file is reproducible from this script alone.

    They live under `reports/` and NOT in `zoo/corpus/rf/`, deliberately: every
    S3 study globs that directory, so six files dropped into it would silently
    change the denominator of every corpus number in this project.

    `wrong_sample_rate.wav` is the interesting one - the samples are a clean
    200 kHz QPSK capture and the HEADER says 48 kHz. Nothing is wrong with the
    signal; the file lies about it, which is what a mislabelled upload is.

    WRITTEN AS 32-BIT FLOAT, NOT PCM_16 LIKE THE CORPUS - because PCM_16
    DESTROYED ONE OF THE SIX
    ------------------------------------------------------------------------
    The corpus is PCM_16 and the first version of this followed it. Checked
    afterwards rather than assumed, and `empty_band.wav` came back with **2
    distinct sample values** over 240 000 samples: at a peak of 4.85e-06, one
    PCM_16 quantum is 3.05e-05, so the whole capture collapsed onto +/-1 LSB.
    The array in memory is thermal noise 120 dB down; the file on disk was a
    one-bit dither pattern. The one property that case exists to test - that no
    decision in the chain is made on an ABSOLUTE level - is exactly the property
    a fixed-point format cannot carry.

    So the six are `subtype="FLOAT"`. `pipeline/s0_ingest.read_wav_iq` calls
    `sf.read`, which returns float64 for any subtype, so they ingest exactly
    like a corpus file; only the on-disk representation differs. The other five
    gain a little fidelity too - `clipped_saturated` no longer requantises a
    signal whose whole point is what clipping did to it.
    """
    import soundfile as sf

    FILE_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for case in THE_SIX:
        iq, declared_fs, _ref = CASES[case](_seed(case, 0))
        iq = np.asarray(iq, dtype=complex)
        stereo = np.stack([iq.real, iq.imag], axis=-1).astype(np.float32)
        peak = float(np.max(np.abs(stereo)))
        # A plain peak-normalise would scale `empty band` (1e-6) up to look
        # like a full-scale signal, destroying the one property that case
        # exists to test. Absolute level is preserved unless the file clips -
        # which is only meaningful because the subtype is FLOAT; see above.
        if peak > 1.0:
            stereo = stereo / peak * 0.9
        name = "_".join(case.replace(":", "").replace("(", "")
                        .replace(")", "").split())
        path = FILE_DIR / f"{name}.wav"
        sf.write(str(path), stereo, int(declared_fs), subtype="FLOAT")
        written.append((case, path.name, declared_fs, peak))
        print(f"  wrote {path.name}  (declared fs {declared_fs:.0f}, "
              f"peak {peak:.3g})")
    return written


# --- rendering ---------------------------------------------------------------

def _num(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _dist(rows):
    counts: dict[str, int] = {}
    for r in rows:
        k = r["raised"] or r["status"]
        counts[k] = counts.get(k, 0) + 1
    return ", ".join(f"{v}x `{k}`" for k, v in sorted(counts.items(),
                                                      key=lambda kv: -kv[1]))


def _fmt(rows):
    def sel(**kw):
        return [r for r in rows if all(str(r.get(k, "")) == str(v)
                                       for k, v in kw.items())]

    out: list[str] = []
    a = out.append
    raised = [r for r in rows if r["raised"]]
    absence = [r for r in rows if r["case"] in ABSENCE]
    false_pos = [r for r in absence if r["status"] == "ok"]
    bad_status = [r for r in rows if not r["raised"] and r["status"] not in VALID]
    nonfinite = [r for r in rows if str(r["finite"]) == "False"]
    ctrl = sel(path="blind search", case="control: clean qpsk")
    ctrl_ok = [r for r in ctrl if r["status"] == "ok"]
    ctrl_ber = [b for b in (_num(r["ber"]) for r in ctrl) if b is not None]

    a("# Adversarial input to S3 — every case returns a status, never a traceback")
    a("")
    a("8 Sep, the \"break it deliberately\" row. Six named inputs, each over")
    a(f"{SEEDS} seeds, through **both** the named-plug-in path and the blind")
    a("search the service actually calls. Regenerate with")
    a("`python reports/s3_adversarial_study.py` (`--render-only` re-renders")
    a("this file from `s3_adversarial.csv`; `--write-files` rewrites the six")
    a("`.wav` files under `reports/s3_adversarial/`).")
    a("")

    a("## 1. The known-answer cell, first")
    a("")
    a("`control: clean qpsk` is a 20 dB QPSK capture with the correct sample")
    a(f"rate. It reads `ok` on **{len(ctrl_ok)} of {len(ctrl)}** seeds, modulation")
    a(f"`{ctrl[0]['modulation'] if ctrl else '?'}`, worst measured BER")
    a(f"**{max(ctrl_ber):.2e}** over {len(ctrl_ber)} seeds — scored with the repo's")
    a("own `corpus.measured_ber`. If that row is not `ok` this harness is broken")
    a("and no other row in this file means anything. **It has already fired once")
    a("today**: the first draft hand-rolled its own transmitter and the control")
    a("came back `low_confidence` on 8 of 8, which is what exposed that three of")
    a("the six cases were being built on a signal S3 already refused.")
    a("")

    a("## 2. The definition of done")
    a("")
    a("| question | result |")
    a("|---|---|")
    a(f"| tracebacks, every path, every case | **{len(raised)}** of {len(rows)} runs |")
    a(f"| statuses outside `{'`/`'.join(VALID)}` | **{len(bad_status)}** |")
    a(f"| non-finite values in an LLR array | **{len(nonfinite)}** |")
    a(f"| **`ok` on a case with no signal in it** | **{len(false_pos)}** of {len(absence)} |")
    a("")
    a("The last row is the one that matters, and it is deliberately not \"`ok` on")
    a("any adversarial case\". Those are two different questions — see §3.")
    a("")

    a("## 3. Absence versus damage")
    a("")
    a("**`ok` is forbidden on the absence cases** (pure noise, DC, empty band,")
    a("all zeros, single impulse): nothing is transmitting, so a lock is a")
    a("confident lie. This is S3's half of the day's gate item, the same question")
    a("Nehal's column asks of S4 as \"uncoded random data must not produce a false")
    a("code detection\".")
    a("")
    a("**`ok` is correct on the degraded cases** (clipped, two overlapping, wrong")
    a("sample rate) when the answer is right — a signal IS present. Scoring these")
    a("the same way would have marked the clipped row a defect: QPSK is")
    a("constant-modulus, clipping at a quarter of peak takes peak-to-average from")
    a("1.72 to 1.02 and leaves the symbols intact, so a receiver that refused it")
    a("would be worse, not safer.")
    a("")

    a("## 4. The six, through the blind search")
    a("")
    a("`estimate()` on the input, then `receive_best` over S2's ranked")
    a("hypotheses — what S3 can do when it is asked properly. **This is not what")
    a("the service currently calls; see §10.**")
    a("")
    a("| case | class | declared fs | statuses over seeds | modulation | reported Rs | measured BER | worst s |")
    a("|---|---|---|---|---|---|---|---|")
    for case in ("control: clean qpsk",) + THE_SIX:
        rs = sel(path="blind search", case=case)
        if not rs:
            continue
        cls = ("control" if case.startswith("control")
               else "absence" if case in ABSENCE else "degraded")
        mods = sorted({r["modulation"] for r in rs if r["modulation"]})
        rates = sorted({round(_num(r["rate_used"], 0) or 0) for r in rs
                        if _num(r["rate_used"]) is not None})
        bers = [b for b in (_num(r["ber"]) for r in rs) if b is not None]
        worst = max(_num(r["secs"], 0) for r in rs)
        rate_s = ", ".join(f"{v:,}" for v in rates if v) or "—"
        ber_s = (f"{min(bers):.2e}–{max(bers):.2e}" if bers else "— no reference")
        a(f"| {case} | {cls} | {_num(rs[0]['declared_fs'], 0):,.0f} | {_dist(rs)} | "
          f"{', '.join(f'`{m}`' for m in mods) or '— none claimed'} | {rate_s} | "
          f"{ber_s} | {worst:.2f} |")
    a("")

    a("### The one real finding: a wrong `fs` is invisible, by construction")
    a("")
    wfs = sel(path="blind search", case="wrong sample rate")
    wrates = sorted({round(_num(r["rate_used"], 0) or 0) for r in wfs})
    wbers = [b for b in (_num(r["ber"]) for r in wfs) if b is not None]
    a("`wrong sample rate` is a clean 200 kHz QPSK capture whose header says")
    a("48 kHz. S3 returns `ok`, modulation `qpsk`, measured BER")
    a(f"{('%.2e' % max(wbers)) if wbers else 'n/a'} — a **completely correct")
    a("demodulation** — and reports `symbol_rate_used` of")
    a(f"{', '.join(f'{v:,} Hz' for v in wrates if v)} against a true 50,000 Hz.")
    a("")
    a("That ratio is exactly 48000/200000. Every stage of S3 works on")
    a("`fs / symbol_rate` — samples per symbol — so a declared `fs` wrong by a")
    a("factor *k* produces a symbol rate wrong by the same *k*, a residual CFO")
    a("wrong by the same *k*, and **every internal consistency check passing**,")
    a("because all of them are ratio-based. `sps_estimated` still reads 4.00007.")
    a("")
    a("**This is not a defect in S3 and S3 cannot fix it.** Absolute time is not")
    a("in the samples; it arrives only from the WAV header or the service's")
    a("`fs_hint` form field. But it is a confidently-wrong *number* in a")
    a("user-visible field carried under an `ok` status, and it is reachable by a")
    a("judge in five seconds without touching the signal. The honest statement is")
    a("that every absolute-frequency quantity S3 reports is *proportional to the")
    a("declared sample rate*, and is only as trustworthy as that header.")
    a("")

    a("### 4.1 A refused result still carries a modulation name")
    a("")
    pn = sel(path="blind search", case="pure noise")
    named = [r for r in pn if r["modulation"]]
    a(f"On **{len(named)} of {len(pn)}** pure-noise seeds the search runs far enough")
    a("to name a modulation before refusing, and `values['modulation']` is left")
    a("populated on the refused result — `2fsk` at 58,954 Hz, with `n_llrs` 0 and")
    a("`status` `failed`. The contract holds: the status is the refusal and there")
    a("is no stream attached to the claim.")
    a("")
    a("It is still worth stating, because the failure it invites is a consumer")
    a("that reads `values['modulation']` without reading `status` first, and gets")
    a("\"2fsk\" for a band containing nothing but noise. Every consumer in this")
    a("repo reads `status` first and none is affected today. **Flagged rather than")
    a("changed**: blanking the field would lose the diagnostic that says which")
    a("hypothesis got furthest, which is what makes a refusal debuggable — the")
    a("house rule is that a check which cannot see must SAY so, and this one does.")
    a("")

    a("### 4.2 The most expensive input in the set is a realistic one")
    a("")
    two = sel(path="blind search", case="two overlapping signals")
    tsecs = [_num(r["secs"], 0) for r in two]
    truns = sorted({str(r["chain_runs"]) for r in two})
    tmods = sorted({r["modulation"] for r in two if r["modulation"]})
    a(f"`two overlapping signals` runs to the chain-run ceiling ({', '.join(truns)})")
    others = [_num(r["secs"], 0) for r in rows
              if r["path"] == "blind search"
              and r["case"] not in ("two overlapping signals",
                                    "control: clean qpsk")]
    a(f"on every seed and costs **{min(tsecs):.2f}–{max(tsecs):.2f} s** here. The next")
    a(f"most expensive adversarial case peaks at {max(others):.2f} s (`empty band`, on")
    a("the one seed in eight where it also runs to the ceiling) and the rest are")
    a("under 1.1 s.")
    a("That is the correct behaviour — there is no right answer to converge on, so")
    a("the search exhausts its list — but it is the number to carry into a budget")
    a("discussion, because two emitters in one band is not a contrived input.")
    a("")
    a(f"On the slower dev box (measured at 2.09x this one, 7 Sep) that is roughly")
    a(f"**{max(tsecs) * 2.09:.1f} s against the 20 s budget** — inside it, with the")
    a("smallest margin of anything measured this week. The corpus worst case is")
    a("6.97 s here for comparison, so this input is not an outlier in cost; it is")
    a("simply the first adversarial one measured at all.")
    a("")
    a(f"The modulation claimed varies across {len(tmods)} families by seed")
    a(f"({', '.join(f'`{m}`' for m in tmods)}) while the measured BER stays at")
    a("0.48 — a coin flip. A receiver with no stable preference, saying")
    a("`low_confidence` every time, is exactly the honest signature for an input")
    a("with two right answers and no way to choose.")
    a("")

    a("## 5. The same inputs through every named plug-in")
    a("")
    a("`MODULATIONS[name].receive(iq, params)` with a plausible rate — what the")
    a("4 Sep unit tests cover, and — per §10 — **what the service actually does")
    a("today**, with `name` hardcoded to `qpsk`. A plug-in handed an explicit rate")
    a("has no search, no rescue and no deadline.")
    a("")
    a("| case | statuses over all plug-ins x seeds | `ok` | tracebacks |")
    a("|---|---|---|---|")
    for case in ("control: clean qpsk",) + THE_SIX:
        rs = sel(path="plug-in", case=case)
        if not rs:
            continue
        a(f"| {case} | {_dist(rs)} | {sum(1 for r in rs if r['status'] == 'ok')} "
          f"| {sum(1 for r in rs if r['raised'])} |")
    a("")

    a("## 6. Degenerate extras")
    a("")
    a("Not named by the row; carried since 4 Sep and re-measured here because")
    a("they cost nothing once the harness exists. Both are absence cases.")
    a("")
    a("| case | blind search | plug-in path |")
    a("|---|---|---|")
    for case in ("all zeros", "single impulse"):
        b = sel(path="blind search", case=case)
        p = sel(path="plug-in", case=case)
        if b:
            a(f"| {case} | {_dist(b)} | {_dist(p)} |")
    a("")

    a("## 7. The six files")
    a("")
    a("`--write-files` writes seed 0 of each case to `reports/s3_adversarial/`")
    a("as a stereo (I, Q) WAV at the declared rate, so they ingest through S0")
    a("like any corpus file. They are **not** in `zoo/corpus/rf/` on purpose:")
    a("every S3 study globs that directory and six extra files would silently")
    a("move the denominator of every corpus number in this project.")
    a("")
    a("**They are 32-bit float, not PCM_16 like the corpus, and that is not")
    a("cosmetic.** The first version followed the corpus format; checked")
    a("afterwards, `empty_band.wav` had **2 distinct sample values** across")
    a("240,000 samples. At a peak of 4.85e-06 one PCM_16 quantum is 3.05e-05, so")
    a("the capture collapsed onto ±1 LSB — a one-bit dither pattern where the")
    a("array in memory is thermal noise 120 dB down. **The one property that case")
    a("exists to test is the one a fixed-point format cannot carry.**")
    a("`read_wav_iq` calls `sf.read`, which returns float64 for any subtype, so")
    a("nothing downstream sees a difference.")
    a("")
    a("Regeneration is **sample-exact, not byte-exact**, and the distinction is")
    a("the format's rather than a weakness in the check: libsndfile writes a")
    a("`PEAK` chunk on float WAVs carrying a creation **timestamp**, so all six")
    a("differ at byte 60 and nowhere else.")
    a("`test_the_committed_files_are_reproducible_from_the_study` regenerates into")
    a("a temp directory and compares decoded samples, rate and subtype — which is")
    a("all anything downstream reads.")
    a("")

    a("## 8. Every refusal says why, in numbers")
    a("")
    a("The day's integration line is \"nothing unhandled remains; every failure has")
    a("a message a human can act on\". S3's half, seed 0 of each case, verbatim from")
    a("`reason`:")
    a("")
    a("| case | status | reason |")
    a("|---|---|---|")
    for case in THE_SIX:
        rs = [r for r in sel(path="blind search", case=case) if r["seed"] == "0"]
        if not rs:
            continue
        why = (rs[0].get("reason") or "").strip()
        why = why.replace("|", chr(92) + "|") or (
            "*none, and correctly so — there is nothing to explain*"
            if rs[0]["status"] == "ok" else "*(none)*")
        a(f"| {case} | `{rs[0]['status']}` | {why} |")
    a("")
    a("Each one names the statistic, the threshold it missed and by how much. The")
    a("two `ok` rows carry no reason, which is right — there is nothing to")
    a("explain. `two overlapping signals` also reports its own truncation")
    a("(\"12 of 18 surviving candidates were run and 6 never reached — this is the")
    a("best of what ran, not a survey of the field\"), which is the 7 Sep fix #3")
    a("doing its job on an input it was not written for.")
    a("")

    a("## 9. What the six files found OUTSIDE S3 — for Naidhruv, and one for Dheeraj")
    a("")
    a("Running the six through `python -m service.cli analyze` end to end (S0-S6,")
    a("no tracebacks, every stage returned a status) shows the whole chain's")
    a("verdict on a file containing nothing but noise:")
    a("")
    a("| stage | status | confidence | what its own values say |")
    a("|---|---|---|---|")
    a("| s0_ingest | `ok` | 1.00 | a valid WAV — true |")
    a("| s1_detect | `ok` | **0.98** | `snr_db` **−10.2**, `occupied_bw` 198 kHz of 200, `burst_count` 0 |")
    a("| s2_estimate | `ok` | **0.90** | `symbol_rate` 45,350 Hz, `symbol_rate_score` **0.0** |")
    a("| s3_receive | `failed` | 0.00 | `signal_present: fail`, metric 3.83 against 4.5 |")
    a("")
    a("**S3 is the first stage in the chain that refuses pure noise.** The final")
    a("answer is therefore correct — but a judge reads the stage cards on the way")
    a("to it, and three of them are green and confident on an empty band. That is")
    a("Command Center risk #15 (\"false positive: claims a code where none")
    a("exists — a judge WILL try this\") rendered on screen, and the 8 Sep gate")
    a("calls the false-positive test mandatory for exactly this reason.")
    a("")
    a("**Neither of Dheeraj's stages is at fault, and this was checked rather than")
    a("assumed.** `s1_detect.detect()` returns `status=\"ok\"` whenever it did not")
    a("raise and the array is non-empty — it carries no detection predicate at")
    a("all, because S1 is a measurement stage (PSD, SNR, occupied BW, bursts) and")
    a("not a decision stage. Its numbers are honest: −10.2 dB SNR and 99% of the")
    a("band occupied is precisely what noise looks like. The status is right and")
    a("the *confidence attached to it downstream* is what is wrong.")
    a("")
    a("**Two things in `service/orchestrator.py`, both in the adapters:**")
    a("")
    a("1. **`adapt_s1` (line 293) hardcodes `confidence=0.98` for any `ok`.** It")
    a("   means \"the stage ran\", but it renders as a detection confidence. Every")
    a("   number needed to compute a real one is already in `values` three lines")
    a("   above — `snr_db`, `occupied_bw_hz`, `burst_count`. The attached")
    a("   hypothesis has the same shape: `\"continuous\"` at score **0.95**, with")
    a("   `evidence=\"0 bursts detected\"` — a 95% score whose stated evidence is")
    a("   that nothing was found.")
    a("")
    a("2. **`adapt_s2` (line 338) inverts its own confidence at zero.** The line is")
    a("   `min(1.0, max(0.1, score / 10.0)) if score else 0.9`. A `symbol_rate_score`")
    a("   of exactly **0.0** is falsy, so it takes the `else` branch and renders")
    a("   **0.90**:")
    a("")
    a("   | `symbol_rate_score` | rendered confidence |")
    a("   |---|---|")
    a("   | **0.0** | **0.90** |")
    a("   | 0.5 | 0.10 |")
    a("   | 1.0 | 0.10 |")
    a("   | 5.0 | 0.50 |")
    a("   | 9.0 | 0.90 |")
    a("")
    a("   No evidence at all reports the same confidence as a score of 9, and")
    a("   **nine times** the confidence of a score of 0.5. The guard is testing")
    a("   truthiness where it means \"is present\", and 0.0 is both present and the")
    a("   worst possible score. `pure_noise.wav` hits it on every run.")
    a("")
    a("Neither is S3's to fix and neither has been touched — `service/` is")
    a("Naidhruv's. Both are one-line changes in his adapters, both are reproducible")
    a("from `reports/s3_adversarial/pure_noise.wav`, and the second one is a")
    a("two-character fix (`if score else` -> `if score is not None else`, or drop")
    a("the fallback). Raised here with the measurement attached rather than edited.")
    a("")

    a("## 10. The service never calls the blind search, and demodulates everything as QPSK")
    a("")
    a("**This is the largest finding of the day and it was found by accident** \u2014")
    a("by running the six adversarial files through `python -m service.cli analyze`")
    a("and noticing that all six reported `modulation: qpsk`, including the ones")
    a("`receive_best` calls `16qam` and `2fsk`. It is not S3\u0027s to fix and nothing")
    a("here has been changed; `service/` is Naidhruv\u0027s.")
    a("")
    a("### Measured, 40 random corpus files, both paths")
    a("")
    a("| path | decodes | modulation correct |")
    a("|---|---|---|")
    a("| `receive_best(iq, params_from_s2(s2, fs))` \u2014 what S3 can do | **35/40** | **37/40** |")
    a("| `MODULATIONS[chosen_scheme].receive(...)` \u2014 what the service does | **11/40** | **11/40** |")
    a("")
    a("24 of 40 files decode on one path and not the other. Every disagreement")
    a("has `chosen_scheme == \"qpsk\"` against a true scheme of 2fsk, 4fsk, 8psk or")
    a("16qam. Scored with the repo\u0027s own `corpus.measured_ber` against the")
    a("transmitted bits.")
    a("")
    a("### The chain, read rather than inferred")
    a("")
    a("1. **`adapt_s2` reads a field that does not exist.**")
    a("   `service/orchestrator.py:323` is")
    a("   `order_hint = getattr(raw, \"order_hint\", 0)`. **`S2Result` has no")
    a("   `order_hint`** \u2014 its field is `fsk_order_hint`. So the `getattr` default")
    a("   fires on every input and `order_hint` is **0 on 30 of 30** corpus files")
    a("   measured.")
    a("2. **`order_hint == 0` takes the `else` branch** of the if/elif ladder at")
    a("   `orchestrator.py:341-349`, which returns")
    a("   `[Hypothesis(\"qpsk\", 0.7), Hypothesis(\"bpsk\", 0.3)]` \u2014 always.")
    a("3. **Dheeraj\u0027s classifier is computed and discarded.**")
    a("   `S2Result.modulation_hypotheses` carries the ML ranking and is populated")
    a("   on **28 of 30** files; `adapt_s2` never reads it. On `2fsk_15dB_6028` it")
    a("   says `2fsk` at **0.9987** while the adapter hands S3 `qpsk` at 0.7.")
    a("4. **`orchestrate` takes `s2_res.hypotheses[0].value`** (line 844) \u2014 `qpsk`.")
    a("5. **`_run_s3` (line 856) runs that ONE plug-in**, never `receive_best`. No")
    a("   search, no ranked fallback, no rate rescue, no breadth-first ordering \u2014")
    a("   the whole of `e7b9649` is unreachable from the API and the CLI.")
    a("")
    a("### Why it is invisible")
    a("")
    a("Same shape as the two other integration defects found this week, and the")
    a("third instance of the same species in this one file: a `getattr` against a")
    a("field name that does not exist, silently taking its default. The 7 Sep")
    a("notes already record \u201cone orchestrator test asserting `est.symbol_rate`")
    a("where `S2Result` has `symbol_rate_hz`\u201d. Nothing raises, every stage returns")
    a("`ok`, and the report looks complete \u2014 it is simply wrong about the")
    a("modulation. A corpus file that decodes perfectly in S3\u0027s own tests comes")
    a("back as noise through the service, and no test compares the two paths.")
    a("")
    a("### The fix is small and it is Naidhruv\u0027s")
    a("")
    a("Stated because it is a day before freeze, not to pre-empt his call:")
    a("")
    a("* `adapt_s2` should prefer `raw.modulation_hypotheses` when it is present")
    a("  and fall back to the ladder only when it is not \u2014 that alone restores")
    a("  Dheeraj\u0027s classifier, which is right on 28 of 30.")
    a("* `_run_s3` should call `receive_best(iq, params_from_s2(s2_raw, fs))`, the")
    a("  entry point S3 exposes for exactly this. It reads the ranking as a PRIOR")
    a("  rather than a restriction, so it still recovers files the classifier gets")
    a("  wrong \u2014 which is the difference between 35/40 and 11/40.")
    a("* If neither lands before freeze, the honest fallback is to stop reporting")
    a("  a modulation the service did not determine: `qpsk` is a hardcoded default")
    a("  presented to a judge as a finding.")
    a("")

    if raised:
        a("## Tracebacks")
        a("")
        for r in raised[:10]:
            a(f"- **{r['case']}** / {r['path']} {r['plugin']}: `{r['raised']}`")
        a("")

    return "\n".join(out) + "\n"


def render():
    MD_PATH.write_text(_fmt(read_csv()), encoding="utf-8")
    print(f"wrote {MD_PATH}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--write-files", action="store_true")
    args = ap.parse_args()

    if args.write_files:
        write_files()
    if args.render_only:
        render()
        return
    rows = measure()
    write_csv(rows)
    render()


if __name__ == "__main__":
    main()
