"""9 Sep: does anything in S3 leave the stage as a traceback?

The 9 Sep row is "read S3 end to end looking for anything that can throw, no new
code" and then "guard commits only". Reading is what finds the candidates;
this is what decides which of them are real. It exists because the day's central
claim - 48 unintended throws before the guard pass and 0 after - is worth
nothing if it cannot be re-run.

WHAT IT SWEEPS, AND WHY THE SURFACE IS CUT THIS WAY
---------------------------------------------------
Each plug-in's `receive()` wraps its whole chain in a catch-all that turns any
exception into a `failed` status (`linear.py`, `fsk_plugin.py`). So the useful
question is never "can this function raise" but "can it raise OUTSIDE those two
try blocks", and the sweeps are cut on that line:

    A  the plug-in surface        inside the catch-all; expected clean already
    B  `receive_best`             the orchestrator entry, NO catch-all
    C  `lockcheck` and friends    called directly by reports and other stages
    D  the remaining exports      everything else `__init__` publishes

A came back 216 of 216 clean before any change was made, which is the result
that told the day where to look: everything found on 9 Sep is outside those two
try blocks.

THE KNOWN-ANSWER CELL IS INSIDE EVERY SWEEP, NOT BESIDE IT
----------------------------------------------------------
Every sweep here carries a control - a clean capture, a well-formed parameter
set, a valid constellation order - and the summary prints it FIRST. A probe that
asks "did this raise" passes trivially when the thing under it refuses
everything, and this repo has been bitten by exactly that: 8 Sep's hand-rolled
transmitter made three of six adversarial cases incapable of reporting anything
but a refusal, and the control row is what caught it in one glance.

It caught this script too. The first version of sweep D called `evm_percent`,
`hard_decisions`, `lock_metric` and `costas_loop` with a constellation array
where each takes a `Scheme`, and `estimate_tones` and `fsk_demod_noncoherent`
with more positional arguments than they accept. It reported 220 throws out of
313, essentially all of them the harness calling the wrong signature. A check
that fires on a difference it created is worse than no check, because the next
real firing gets waved through - so the signatures are taken from
`inspect.signature` and the control row is read before any other.

RUN IT
------
    ./.venv/Scripts/python.exe reports/s3_guard_probe.py

Exits non-zero if any UNEXPECTED throw is found, so it can be used as a check
rather than only as a report. The expected ones are listed in `EXPECTED` below,
each with the reason it is a contract rather than a defect.
"""
from __future__ import annotations

import os
import sys
import zlib
import traceback
import warnings

sys.path.insert(0, os.getcwd())          # a script outside the tree cannot
                                         # import the repo without this; see
                                         # day2day §4, it cost two dead runs

import numpy as np                                            # noqa: E402

warnings.filterwarnings("ignore")        # numpy's overflow/invalid warnings on
                                         # deliberately degenerate input are the
                                         # point, not a finding

import pipeline.s3_receive as S3                              # noqa: E402
from pipeline.s3_receive.search import (params_from_s2,       # noqa: E402
                                        receive_best)
from registry import CODES, MODULATIONS                       # noqa: E402
from tests.fixtures.corpus import synth                       # noqa: E402


EXPECTED = {
    # (function, ValueError) pairs that are the documented contract, not a
    # defect. Each raises deliberately, with a message that names the input.
    "gardner_sync": "refuses a record too short for the timing loop, by design",
    "fsk_demod_noncoherent": "refuses a record too short to demodulate, by design",
    "bits_per_symbol": "refuses an order that is not a power of two, by design",
    "constellation": "refuses an order the PSK builder does not carry, by design",
    "scheme": "refuses an unregistered scheme name, by design",
    "matched_filter": "refuses a roll-off outside (0, 1] and a tap count over "
                      "the 8191 cap, by design",
    "rrc_taps": "same bounds as matched_filter, by design",
    # Reported on 9 Sep and deliberately NOT guarded: `estimate_occupied_band`
    # has no caller in the repo, and `estimate_rolloff`'s single caller sits
    # behind a record-length check that already refuses a capture this short.
    # Inventing an occupied band for an empty array is a worse answer than a
    # raise; it is the message that is wrong, not the refusal.
    "estimate_rolloff": "IndexError on an EMPTY capture - reported 9 Sep, "
                        "unreachable, message is wrong not the refusal",
    "estimate_occupied_band": "IndexError on an EMPTY capture - reported 9 Sep, "
                              "unreachable, no caller in the repo",
}


class Sweep:
    """One family of cases, with its control read first."""

    def __init__(self, name: str, blurb: str) -> None:
        self.name, self.blurb = name, blurb
        self.n = 0
        self.throws: list[tuple[str, str, str]] = []
        self.control_ok: bool | None = None

    def run(self, label: str, fn, *a, **k):
        self.n += 1
        try:
            return fn(*a, **k)
        except Exception as exc:                       # noqa: BLE001
            fname = getattr(fn, "__name__", str(fn))
            self.throws.append((label, fname, f"{type(exc).__name__}: {exc}"))
            return None

    @property
    def unexpected(self) -> list[tuple[str, str, str]]:
        return [t for t in self.throws if t[1] not in EXPECTED]


def _signal(n_bits=8000, snr=15.0, scheme="qpsk", seed=5):
    return synth(scheme, n_bits=n_bits, snr_db=snr, sps=4, seed=seed)


def _captures(good):
    return {
        "empty": np.zeros(0, np.complex128),
        "one sample": np.ones(1, np.complex128),
        "all zeros": np.zeros(40000, np.complex128),
        "all nan": np.full(40000, np.nan + 1j * np.nan),
        "all inf": np.full(40000, np.inf + 0j),
        "huge 1e300": np.full(40000, 1e300 + 1e300j),
        "tiny 1e-300": np.full(40000, 1e-300 + 0j),
        "real-valued": np.random.default_rng(1).normal(size=40000),
        "int dtype": np.arange(40000, dtype=np.int32),
        "2-D": np.zeros((200, 200), np.complex128),
        "python list": [0.1 + 0.2j] * 4000,
        "CONTROL clean": good,
    }


def sweep_a(good, fs, rs) -> Sweep:
    """Every plug-in method against every hostile capture."""
    s = Sweep("A plug-in surface",
              "inside receive()'s catch-all; expected clean already")
    params = {"fs": fs, "symbol_rate": rs}
    for plug in MODULATIONS.values():
        for cname, iq in _captures(good).items():
            for meth in ("receive", "demodulate", "classify_features"):
                label = f"{plug.name}.{meth} [{cname}]"
                if meth == "classify_features":
                    s.run(label, plug.classify_features, iq)
                else:
                    s.run(label, getattr(plug, meth), iq, params)
    res = MODULATIONS["qpsk"].receive(good, params)
    s.control_ok = res.status == "ok"
    return s


def sweep_b(good, fs, rs) -> Sweep:
    """`receive_best` against hostile PARAMETERS - the entry with no catch-all."""
    s = Sweep("B receive_best", "the orchestrator entry point, no catch-all")
    noise = (np.random.default_rng(2).normal(size=40000)
             + 1j * np.random.default_rng(3).normal(size=40000))
    P = {
        "CONTROL": dict(fs=fs, symbol_rate=rs),
        "fs=0": dict(fs=0.0, symbol_rate=rs),
        "fs absent": dict(symbol_rate=rs),
        "fs inf": dict(fs=np.inf, symbol_rate=rs),
        "fs nan": dict(fs=np.nan, symbol_rate=rs),
        "fs negative": dict(fs=-fs, symbol_rate=rs),
        "fs numeric string": dict(fs="200000", symbol_rate=rs),
        "fs junk string": dict(fs="wide", symbol_rate=rs),
        "fs None": dict(fs=None, symbol_rate=rs),
        "empty params": dict(),
        "rate=0": dict(fs=fs, symbol_rate=0.0),
        "rate nan": dict(fs=fs, symbol_rate=np.nan),
        "rate inf": dict(fs=fs, symbol_rate=np.inf),
        "rate negative": dict(fs=fs, symbol_rate=-rs),
        "rate numeric string": dict(fs=fs, symbol_rate="50000"),
        "rate junk string": dict(fs=fs, symbol_rate="fast"),
        "rate None": dict(fs=fs, symbol_rate=None),
        "rate above fs": dict(fs=fs, symbol_rate=fs * 4),
        "rate tiny": dict(fs=fs, symbol_rate=1e-12),
        "sps only": dict(fs=fs, sps=4.0),
        "sps=0": dict(fs=fs, sps=0.0),
        "cfo nan": dict(fs=fs, symbol_rate=rs, cfo_hz=np.nan),
        "cfo inf": dict(fs=fs, symbol_rate=rs, cfo_hz=np.inf),
        "cfo huge": dict(fs=fs, symbol_rate=rs, cfo_hz=1e18),
        "beta=0": dict(fs=fs, symbol_rate=rs, beta=0.0),
        "beta=5": dict(fs=fs, symbol_rate=rs, beta=5.0),
        "beta nan": dict(fs=fs, symbol_rate=rs, beta=np.nan),
        "rate hyps junk": dict(fs=fs, symbol_rate_hypotheses=[
            ("x", "y"), None, 3, (np.nan, 1.0), (np.inf, 2.0)]),
        "rate hyps all nan": dict(fs=fs, symbol_rate_hypotheses=[
            (np.nan, 1.0), (np.nan, 2.0)]),
        "rate hyps empty tuple": dict(fs=fs, symbol_rate=rs,
                                      symbol_rate_hypotheses=[()]),
        "cfo hyps junk": dict(fs=fs, symbol_rate=rs, cfo_hypotheses=[
            (np.nan, 1, 1.0), "z", (np.inf, 1, 1.0)]),
        "mod hyps junk": dict(fs=fs, symbol_rate=rs, modulation_hypotheses=[
            ("nope", 1.0), (None, None), 42]),
        "mod hyps nan score": dict(fs=fs, symbol_rate=rs,
                                   modulation_hypotheses=[("qpsk", np.nan)]),
        "mod hyps negative": dict(fs=fs, symbol_rate=rs, modulation_hypotheses=[
            ("qpsk", -5.0), ("bpsk", -9.0)]),
        "1000 rate hyps": dict(fs=fs, symbol_rate_hypotheses=[
            (rs * (1 + i * 1e-7), 1.0) for i in range(1000)]),
    }
    IQ = {"CONTROL good": good, "noise": noise,
          "empty": np.zeros(0, np.complex128),
          "zeros": np.zeros(40000, np.complex128),
          "nan": np.full(40000, np.nan + 0j)}
    for pname, p in P.items():
        for iname, iq in IQ.items():
            res = s.run(f"receive_best [{pname} / {iname}]",
                        receive_best, iq, dict(p), budget_s=4.0)
            if res is not None and res.status not in ("ok", "low_confidence",
                                                      "failed"):
                s.throws.append((f"{pname}/{iname}", "receive_best",
                                 f"OFF-CONTRACT status {res.status!r}"))

    class Bare:
        pass

    class ChangedType:
        """Fields present, wrong type - the shape 8 Sep's `order_hint` took."""
        symbol_rate_hz = "fifty"
        cfo_hz = None
        fs = None
        symbol_rate_hypotheses = 7
        cfo_hypotheses = None
        modulation_hypotheses = "qpsk"

    for oname, obj in [("None", None), ("bare", Bare()),
                       ("changed type", ChangedType()), ("int", 5)]:
        for fsarg in (None, fs, 0.0):
            s.run(f"params_from_s2 [{oname} fs={fsarg}]",
                  params_from_s2, obj, fsarg)

    ctrl = receive_best(good, dict(P["CONTROL"]), budget_s=8.0)
    s.control_ok = ctrl.status == "ok"
    return s


def sweep_c(good, fs, rs) -> Sweep:
    """`lockcheck`, `softmap`, `bitmap` and the LDPC decode path, called direct."""
    from pipeline.s3_receive import lockcheck as LC
    s = Sweep("C lockcheck / softmap / ldpc",
              "exported, called directly by reports and other stages")
    EMPTY = np.zeros(0, np.complex128)
    NANS = np.full(20000, np.nan + 0j)
    sig = good[:20000]

    for fsv in (0.0, -1.0, np.nan, np.inf, 1e-30, fs):
        for x, xn in ((sig, "sig"), (EMPTY, "empty"), (NANS, "nans")):
            for fam in ("psk", "fsk"):
                s.run(f"signal_presence fs={fsv} {xn} {fam}",
                      LC.signal_presence, x, fsv, rs, fam)
                s.run(f"strongest_line fs={fsv} {xn} {fam}",
                      LC.strongest_line, x, fsv, fam)
                s.run(f"symbol_rate_line fs={fsv} {xn} {fam}",
                      LC.symbol_rate_line, x, fsv, rs, fam)
            s.run(f"carrier_alignment fs={fsv} {xn}",
                  LC.carrier_alignment, x, fsv, rs)
            s.run(f"carrier_offset fs={fsv} {xn}", LC.carrier_offset, x, fsv)

    for r in (0.0, -rs, np.nan, np.inf, 1e-12, 1e12):
        s.run(f"signal_presence rate={r}", LC.signal_presence, sig, fs, r, "psk")
        s.run(f"carrier_alignment rate={r}", LC.carrier_alignment, sig, fs, r)

    s.run("output_usable nan", LC.output_usable, float("nan"))
    s.run("output_usable inf", LC.output_usable, float("inf"))
    s.run("alphabet_used empty symbols", LC.alphabet_used, EMPTY,
          S3.SCHEMES["bpsk"].points)
    s.run("alphabet_used empty constellation", LC.alphabet_used, sig[:100], EMPTY)
    s.run("alphabet_used nans", LC.alphabet_used, NANS, S3.SCHEMES["bpsk"].points)
    s.run("tone_alias nan", LC.tone_alias, float("nan"), 1000.0)
    s.run("tone_alias zero spacing", LC.tone_alias, 10.0, 0.0)
    s.run("llr_health empty", S3.llr_health, np.zeros(0))
    s.run("llr_health nans", S3.llr_health, np.full(100, np.nan))

    if "ldpc" in CODES:
        ld = CODES["ldpc"]
        H = np.zeros((4, 8), dtype=np.uint8)
        for i in range(4):
            H[i, i] = 1
            H[i, 4 + i] = 1
        P = {"H": H}
        s.run("ldpc empty llrs", ld.decode, np.zeros(0), P)
        s.run("ldpc short llrs", ld.decode, np.zeros(3), P)
        s.run("ldpc nan llrs", ld.decode, np.full(80, np.nan), P)
        s.run("ldpc inf llrs", ld.decode, np.full(80, np.inf), P)
        s.run("ldpc offset past the end", ld.decode, np.zeros(80),
              dict(P, llr_start_bit=200, llr_start_bit_tolerance=500))
        s.run("ldpc no params", ld.decode, np.zeros(80), {})
        s.run("ldpc validate empty", ld.validate, np.zeros(0))

    # CONTROL: the same checks on a good signal at a real rate must not refuse.
    s.control_ok = bool(
        LC.strongest_line(sig, fs, "psk") is not None
        and not LC.signal_presence(sig, fs, rs, "psk").failed)
    return s


def sweep_d(good, fs, rs) -> Sweep:
    """Everything else `pipeline.s3_receive.__init__` exports.

    Signatures taken from the real functions - see the module docstring for why
    that sentence is here.
    """
    s = Sweep("D remaining exports", "the rest of the published surface")
    sch = S3.SCHEMES["qpsk"]
    const = sch.points
    # One generator PER CASE, not one stream shared across them. A shared
    # stream is deterministic within a run and changes every case after any
    # case you insert, which is 8 Sep's mistake in this repo: `empty band`
    # changed verdict between two runs of what looked like the same experiment
    # because a case had been added above it. Seeding by name means a case's
    # data depends on the case and on nothing else.
    def _rng(name: str):
        return np.random.default_rng(zlib.crc32(name.encode()) & 0xFFFFFFFF)

    r_known, r_noise = _rng("known-answer"), _rng("noise")
    # CONTROL: a clean recovered QPSK stream must pass every one of these.
    known = np.tile(const, 800) + 0.01 * (r_known.normal(size=3200)
                                          + 1j * r_known.normal(size=3200))
    arrs = [("empty", np.zeros(0, np.complex128)),
            ("zeros", np.zeros(3000, np.complex128)),
            ("nan", np.full(3000, np.nan + 0j)),
            ("inf", np.full(3000, np.inf + 0j)),
            ("noise", r_noise.normal(size=3000)
                      + 1j * r_noise.normal(size=3000)),
            ("one sample", np.ones(1, complex)),
            ("CONTROL known-answer", known)]

    for an, a in arrs:
        s.run(f"evm_percent {an}", S3.evm_percent, a, sch)
        s.run(f"hard_decisions {an}", S3.hard_decisions, a, sch)
        s.run(f"magnitude_dispersion {an}", S3.magnitude_dispersion, a)
        s.run(f"cumulants {an}", S3.cumulants, a)
        s.run(f"estimated_ber {an}", S3.estimated_ber, np.real(a))
        s.run(f"estimate_noise_variance {an}", S3.estimate_noise_variance, a, const)
        s.run(f"lock_metric {an}", S3.lock_metric, a, sch)
        s.run(f"estimate_rolloff {an}", S3.estimate_rolloff, a, fs, rs)
        s.run(f"estimate_occupied_band {an}", S3.estimate_occupied_band, a, fs)
        s.run(f"cma_equalise {an}", S3.cma_equalise, a)
        s.run(f"mma_equalise {an}", S3.mma_equalise, a, const)
        s.run(f"dispersion_constants {an}", S3.dispersion_constants, a)
        for order in (2, 4, 8):
            s.run(f"estimate_tones {an} M={order}", S3.estimate_tones, a, order)
        for sps in (2.0, 4.0, 8.0):
            s.run(f"gardner_sync {an} sps={sps}", S3.gardner_sync, a, sps)
            s.run(f"fsk_demod_noncoherent {an} sps={sps}",
                  S3.fsk_demod_noncoherent, a, sps)
            s.run(f"costas_loop {an} sps={sps}", S3.costas_loop, a, sch)
    for o in (0, -4, 2, 3, 4, 8, 16):
        s.run(f"constellation {o}", S3.constellation, o)
        s.run(f"bits_per_symbol {o}", S3.bits_per_symbol, o)
    noise = dict(arrs)["noise"]          # by name; an index would re-break on
                                        # any case inserted above it
    for beta in (0.0, 0.01, 0.35, 1.0, 1.5, np.nan):
        for sps in (2.0, 4.0, 8.0, np.nan):
            s.run(f"matched_filter beta={beta} sps={sps}",
                  S3.matched_filter, noise, beta, sps)
            s.run(f"rrc_taps beta={beta} sps={sps}", S3.rrc_taps, beta, sps)
    for nm in ("qpsk", "nope", "", None, 7):
        s.run(f"scheme {nm!r}", S3.scheme, nm)

    s.control_ok = float(S3.evm_percent(known, sch)) < 10.0
    return s


def main() -> int:
    good, fs, rs, _ = _signal()
    print(f"s3 guard probe - signal {good.size} samples, fs {fs:.0f}, "
          f"Rs {rs:.0f}\n")
    sweeps = [sweep_a(good, fs, rs), sweep_b(good, fs, rs),
              sweep_c(good, fs, rs), sweep_d(good, fs, rs)]

    print(f"{'sweep':30s} {'cases':>6s} {'control':>9s} {'expected':>9s} "
          f"{'UNEXPECTED':>11s}")
    print("-" * 70)
    total = unexpected = 0
    for s in sweeps:
        exp = len(s.throws) - len(s.unexpected)
        total += s.n
        unexpected += len(s.unexpected)
        print(f"{s.name:30s} {s.n:6d} {'ok' if s.control_ok else 'BROKEN':>9s} "
              f"{exp:9d} {len(s.unexpected):11d}")
    print("-" * 70)
    print(f"{'total':30s} {total:6d} {'':>9s} {'':>9s} {unexpected:11d}\n")

    broken = [s.name for s in sweeps if not s.control_ok]
    if broken:
        print("CONTROL CELL BROKEN in: " + ", ".join(broken))
        print("Every 'did not throw' below is meaningless until that is fixed.")
        return 2

    for s in sweeps:
        for label, fname, exc in s.unexpected:
            print(f"UNEXPECTED  {label}\n            {exc}")
    if unexpected:
        print(f"\n{unexpected} unexpected throw(s). See EXPECTED for the ones "
              "that are contract.")
        return 1
    print("no unexpected throws; every raise below is in EXPECTED:")
    for name, why in sorted(EXPECTED.items()):
        print(f"  {name:26s} {why}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                  # noqa: BLE001
        traceback.print_exc()
        print("\nPROBE ITSELF FAILED - this is not a result about S3.")
        sys.exit(3)
