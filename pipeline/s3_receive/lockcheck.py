"""Lock-failure detection - knowing when the receiver has NOT locked.

4 Sep, Block B. Owner: Anvith.

Until today S3 decided it was locked from one number: `|E[(y/|y|)^S]|`, the
S-th power carrier lock metric, against a per-family threshold. That number is
a good phase-noise detector and it is **blind by construction to the failure
the pipeline actually produces**.

THE FAILURE, MEASURED
---------------------
S2 hands S3 a carrier offset. On the 36-file RF corpus it hands over one that
is wrong on 33 of them, and wrong in one specific way: `estimate_cfo` raises
the signal to the M-th power and takes the strongest line, and for a
pulse-shaped stream the strongest line is the **symbol-rate** line, not
`M x cfo`. So the reported offset comes back at about `Rs / M`.

De-rotating by `Rs / M` advances the constellation by exactly one symmetry
step per symbol - 90 degrees a symbol for QPSK, 180 for BPSK, 45 for 8-PSK.
And `|E[u^S]|` is *invariant* under exactly that: `(u e^{j2pi/S})^S == u^S`.
The lock metric cannot see it, in principle, not by accident.

What that produced, before this module existed:

    qpsk_20dB_2011   status ok   confidence 0.985
                     estimated_output_ber 0.000000   ACTUAL BER 0.485

**19 of the 36 corpus files**, reported as a clean lock over a coin flip.
`reports/s3_lock_gate.md` measures that rather than remembering it: the study
reconstructs the old verdict from the per-check results of the same runs, so
the number can be regenerated. It is a floor, not an exact count - the
reconstruction cannot speak for the four files where today's build gives up
before the carrier loop ever runs.

That is the single worst thing a stage can do, because every consumer reads
`status` before it reads anything else, and Nehal's S4 pre-flight reads
`estimated_output_ber` before it spends its search budget.

THE PRINCIPLE
-------------
One number cannot detect its own blind spot. So lock is now a set of
INDEPENDENT checks against DIFFERENT evidence, and any one of them can veto:

    signal_present    a cyclostationary line at the claimed symbol rate.
                      Spectral, not constellation-based, so it survives every
                      carrier and timing error there is.
    carrier_aligned   the spectrum is still centred after the CFO hypothesis
                      has been applied. Spectral again, and it is precisely
                      what the S-th power metric cannot see.
    timing_converged  } the two loops that run BEFORE the carrier loop, whose
    equaliser_ok      } verdicts were being computed and then thrown away.
    carrier_locked    the S-th power metric. Kept - it is right about what it
                      is right about.
    output_usable     the receiver's OWN estimated output error rate. A stage
                      claiming success while reporting a fifth of its output
                      wrong is contradicting itself, and two files did exactly
                      that before this was written down.
    alphabet_used     linear only: does the cloud use the whole alphabet
                      this hypothesis claims? The only one that can catch a
                      constellation which CONTAINS the transmitted one -
                      QPSK read as 16-QAM locks perfectly and decodes to
                      noise.
    tone_alias        FSK only: the frequency twin of the rotation ambiguity.
                      An offset of one tone spacing maps the tone bank onto
                      itself and slips every symbol label by one.

Checks are THREE-valued: pass, fail, or unknown. A check that cannot see - no
symbol rate supplied, a record too short to measure on - returns `unknown` and
is not counted either way. A check that silently returns `pass` when it has no
evidence is worse than no check at all, because it looks like corroboration.

WHAT IT IS NOT
--------------
None of this is modulation classification, and none of it is a replacement for
S2. `signal_present` verifies a hypothesis S2 handed over; it does not search
for one. The two statistics it uses are the same two S2 estimates from,
deliberately: if S3 measured the line a different way it could disagree with S2
about a signal both are looking at, and there would be no way to tell which was
right.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sps_signal
from scipy.signal import medfilt

__all__ = ["Check", "LockReport", "symbol_rate_line", "strongest_line",
           "carrier_offset",
           "signal_presence", "carrier_alignment", "output_usable",
           "alphabet_used", "tone_alias", "loop_check",
           "PASS", "FAIL", "UNKNOWN", "LINE_ABSENT_LIMIT",
           "LINE_PRESENT_LIMIT", "CARRIER_OFFSET_LIMIT", "OUTPUT_BER_LIMIT",
           "ALPHABET_ENTROPY_LIMIT"]

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"

LINE_ABSENT_LIMIT = 4.5
LINE_PRESENT_LIMIT = 8.0
"""Two levels, not one, on the height of the symbol-rate line over its local
median. Below `ABSENT` the check says no; at or above `PRESENT` it says yes;
in between it says `unknown` and lets the rest of the chain decide.

It was one threshold at 6.0 for about an hour, and the hour was informative.
6.0 has a 3.4x margin below the weakest corpus file, which looks decisive - and
it rejected 2-FSK at 1.5 dB over 8 samples/symbol, a signal that demodulates to
a measurable bit error rate and that `test_estimated_ber_tracks_actual` exists
to check. One number was being asked to answer two different questions:
"is this definitely noise" and "is this definitely a signal". Those have
different answers and there is a band between them where the honest reply is
neither.

MEASURED. Real signals, at the symbol rate they were sent at:

    36-file RF corpus                   20.2 .. 185.3  (weakest 16-QAM at 4 dB)
    BPSK 1.0 dB / QPSK 3.5 / 8-PSK 9.5     30.6, 45.7, 90.4
    4-FSK 2.5 dB                              34.7
    2-FSK 1.5 dB, 8 samples/symbol             5.5   <- the awkward one

Things that are not the signal being looked for:

    corpus at 0.24x / 0.61x / 1.31x / 2x the true rate     <= 3.0
    pure noise, 192 draws per length      60k samples 3.56, 80k 2.83,
                                         120k 2.94, 200k 2.71, 1.9M 1.42
    noise plus a DC term                      3.42
    a chirp across the band                   3.40
    a clipped square wave                     2.85
    two overlapping tones                     4.57

So `ABSENT = 4.5` clears every noise-shaped input measured, with 1.3x over the
worst single draw of 192 at the shortest record length and 1.5x over anything
at the lengths the adversarial tests actually use. `PRESENT = 8.0` sits 2.5x
under the weakest corpus file. Two overlapping tones land in the band and are
refused later by the carrier and tone-margin checks, which is the right place:
two tones genuinely are a structured signal, they are simply not one this
receiver can lock to.

The noise ceiling falls with record length because `_averaged_spectrum` steadies
the floor it is measured against. `ABSENT` is set from the SHORTEST record
tested, so a longer capture only widens the margin.
"""

CARRIER_OFFSET_LIMIT = 0.03
"""Residual carrier offset, as a fraction of the symbol rate, above which the
CFO hypothesis is rejected.

MEASURED, same corpus, by the spectral-symmetry estimator below:

    raw captures (true offset 0)                |offset| <= 635 Hz  = 0.013 Rs
    after de-rotating by S2's reported offset    |offset| >= 3188 Hz = 0.064 Rs

0.03 Rs sits 2.4x above the worst honest reading and 2.1x below the smallest
dishonest one. At Rs = 50 kHz that is 1.5 kHz, which is also comfortably
inside the Costas loop's own pull-in range (max_freq 0.25 rad/symbol, about
2.0 kHz here) - so a hypothesis this check PASSES is one the loop can finish,
which is the property that makes the limit meaningful rather than arbitrary.
"""

OUTPUT_BER_LIMIT = 0.05
"""The receiver's own estimated output bit error rate, above which it may not
claim `ok` whatever else passed.

A self-consistency check, and it exists because two files got past everything
else without it. The 2-FSK plug-in, run over an 8-PSK capture, finds two tones
with a mean margin of 0.319 - comfortably over its 0.15 threshold - and returns
`status: ok` while estimating its OWN output bit error rate at 0.19. The real
rate was 0.48. Nothing was lying: the tone bank really did separate two peaks.
The receiver was simply claiming success in the same breath as reporting that
its output was a fifth wrong.

MEASURED on the 36-file corpus. Files that decode estimate at most 0.0122
(16-QAM at 8 dB, actual 0.0149). Files that lock onto the wrong thing estimate
0.19 and 0.36. 0.05 is 4x above the first group and 3.8x below the second, and
it is also above the 3% raw rate Nehal measured as the ceiling for statistical
code recovery - so it can never veto a stream S4 could have used.
"""

ALPHABET_ENTROPY_LIMIT = 0.90
"""How evenly the received cloud must use the alphabet the hypothesis claims,
as a normalised entropy over hard decisions. 1.0 is uniform over all M points.

THE CASE THIS EXISTS FOR. QPSK's four points are a SUBSET of 16-QAM's sixteen
and of 8-PSK's eight. Run a QPSK capture through the 16-QAM plug-in and nothing
is wrong with the reception: every symbol lands exactly on a legal constellation
point, so the decision-directed noise variance comes out tiny, the LLRs come out
enormous, and the receiver reports

    status ok   confidence 0.984   estimated_output_ber 1.8e-21
    ACTUAL BER 0.482

Every other check in this module asks whether the receiver locked to the
constellation it was TOLD to assume. None of them can ask whether that was the
right constellation, because a four-point cloud is a perfectly good 16-QAM
reception in which twelve points happen never to be used. This check asks
exactly that: a real 16-QAM stream uses all sixteen.

MEASURED, four linear schemes x four hypotheses x 4-25 dB:

    correct hypothesis                     >= 0.992  (min over 28 runs)
    wrong hypothesis that still said `ok`  <= 0.670  (qpsk seen as 8-PSK)

0.90 sits 1.10x under the worst correct reading and 1.34x over the worst wrong
one. The statistic is bounded in [0, 1] and the mechanism is structural rather
than statistical - an unused constellation point is unused - which is why the
margin does not move with SNR the way an amplitude measure would.

IT VETOES, IT NEVER CONFIRMS, and the 4 dB column is why. Noise scatters
symbols across every point, so a wrong hypothesis at 4 dB reads 0.95-0.99 and
this check goes blind. Those files are refused by the carrier and output checks
instead - which is the whole design: independent evidence, and the one that
cannot see says nothing.

It also does not fire in the other direction. 16-QAM seen through the QPSK
plug-in reads 1.000, because four points really are being used evenly; that
hypothesis is refused by `carrier_locked` instead.
"""

_LINE_NFFT = 1 << 18


@dataclass
class Check:
    """One piece of evidence about whether the receiver locked."""

    name: str
    verdict: str                  # PASS | FAIL | UNKNOWN
    detail: str = ""
    value: float | None = None
    limit: float | None = None

    @property
    def failed(self) -> bool:
        return self.verdict == FAIL


@dataclass
class LockReport:
    """The composite verdict, and every check that produced it."""

    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> "LockReport":
        self.checks.append(check)
        return self

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.failed]

    @property
    def locked(self) -> bool:
        """True only when no applicable check failed.

        `unknown` does not vote. A report of nothing but `unknown` therefore
        reads as locked, which is why callers must not build one - see
        `signal_presence`, which is the check that refuses to be unknown on any
        input carrying energy and a symbol rate.
        """
        return not self.failures

    @property
    def signal_present(self) -> bool:
        """False only when the presence check actively said no.

        Kept separate from `locked` because the two mean different things to a
        caller: 'there is nothing here of this description' is a reason to
        stop, and 'there is something here but I did not lock to it' is a
        reason to try another hypothesis.
        """
        for c in self.checks:
            if c.name == "signal_present":
                return not c.failed
        return True

    @property
    def reason(self) -> str | None:
        f = self.failures
        return "; ".join(c.detail for c in f) if f else None

    def as_values(self) -> dict:
        """The flat form that goes into `S3Result.values`."""
        return {
            "lock_checks": {c.name: c.verdict for c in self.checks},
            "lock_failures": [c.name for c in self.failures],
            "lock_metrics": {c.name: c.value for c in self.checks
                             if c.value is not None},
        }


# --- the two spectral statistics -------------------------------------------

def _next_pow2(n: int) -> int:
    return 1 << (int(n) - 1).bit_length()


def _averaged_spectrum(y: np.ndarray, fs: float,
                       nseg: int = _LINE_NFFT) -> tuple[np.ndarray, np.ndarray]:
    """Welch-averaged amplitude spectrum of a real sequence.

    The first version of this called `np.fft.rfft(y * hanning(y.size), n)` with
    `n` capped at 2^18. That silently TRUNCATES: numpy's `n` argument crops the
    input rather than transforming all of it, so a 1.9-million-sample record
    contributed its first 262 144 samples and nothing else - 87% of the
    evidence thrown away, and no way to tell from the answer.

    Averaging over 50%-overlapped segments uses the whole record and divides
    the VARIANCE of the noise floor by the segment count. It does not raise a
    real line's score - incoherent averaging leaves the peak-to-median ratio of
    a coherent line roughly where it was, and the first version of this comment
    claimed otherwise before the measurement was run. What it does is pull the
    floor's upper tail in, which is the half of the separation that was
    actually loose: the largest score pure noise reached over 192 draws falls
    from 3.56 at 60 000 samples to 1.42 at 1.9 million.

    Cost on the real corpus (79 796 to 638 764 samples): median 8 ms, worst
    28 ms. That is what makes it affordable in front of a 200-1000 ms chain.
    """
    n = min(nseg, _next_pow2(y.size))
    if y.size <= n:
        spec = np.abs(np.fft.rfft(y * np.hanning(y.size), n))
        return spec, np.fft.rfftfreq(n, d=1.0 / fs)

    win = np.hanning(n)
    step = n // 2
    starts = range(0, y.size - n + 1, step)
    acc = np.zeros(n // 2 + 1, dtype=np.float64)
    count = 0
    for s in starts:
        acc += np.abs(np.fft.rfft(y[s:s + n] * win)) ** 2
        count += 1
    return np.sqrt(acc / max(count, 1)), np.fft.rfftfreq(n, d=1.0 / fs)


def _cyclo_spectrum(x: np.ndarray, fs: float,
                    family: str) -> tuple[np.ndarray, np.ndarray] | None:
    """The family's cyclostationary statistic, Welch-averaged.

    Linear modulation puts a line at the symbol rate in the squared magnitude;
    FSK does not, because its envelope is constant, so the FSK branch uses the
    derivative of the instantaneous frequency instead - a train of impulses at
    the symbol boundaries. Both are the statistics `pipeline/s2_estimate.py`
    searches.

    Split out of `symbol_rate_line` on 5 Sep so that `strongest_line` reads the
    same spectrum rather than a second copy of it. Two implementations of one
    statistic is the failure `tests/fixtures/corpus.py` deleted a whole fixture
    to avoid: they agree with each other and nothing checks either.

    Returns None on anything unmeasurable, so callers give one answer to
    "there is nothing here to measure" rather than each inventing a sentinel.
    """
    x = np.asarray(x, dtype=np.complex128).ravel()
    if x.size < 256 or float(np.mean(np.abs(x) ** 2)) <= 1e-20:
        return None

    if family == "fsk":
        inst = np.diff(np.unwrap(np.angle(x)))
        if inst.size < 8:
            return None
        y = np.abs(np.diff(medfilt(inst, kernel_size=5)))
    else:
        y = np.abs(x) ** 2

    y = y - np.mean(y)
    if y.size < 64 or not np.any(np.abs(y) > 0):
        return None
    return _averaged_spectrum(y, fs)


def _line_score_at(spec: np.ndarray, k: int) -> float:
    """Height of bin `k` over the median of the spectrum beside it.

    Local rather than global: a global median is dominated by the far spectrum,
    where there is nothing, and would report a large score for any signal at
    all. The line itself is cut out of the neighbourhood before the median.
    """
    if k <= 0 or k >= spec.size - 1:
        return 0.0
    half = max(8, spec.size // 1024)
    lo, hi = max(1, k - 16 * half), min(spec.size, k + 16 * half)
    left, right = spec[lo:max(lo, k - half)], spec[min(hi, k + half):hi]
    neighbourhood = np.concatenate([left, right])
    if neighbourhood.size < 8:
        return 0.0
    med = float(np.median(neighbourhood)) + 1e-30
    # the peak may land a bin either side of the nominal rate
    return float(spec[k - 1:k + 2].max() / med)


def symbol_rate_line(x: np.ndarray, fs: float, symbol_rate: float,
                     family: str) -> float:
    """Height of the cyclostationary line at `symbol_rate`, over local median.

    Told where to look; reports only how strong the line is there. Its twin
    `strongest_line` reads the same spectrum and answers where the line is.

    Returns 0.0 rather than raising on anything unmeasurable.
    """
    if not np.isfinite(symbol_rate) or symbol_rate <= 0:
        return 0.0
    if symbol_rate >= fs / 2.0:
        return 0.0

    got = _cyclo_spectrum(x, fs, family)
    if got is None:
        return 0.0
    spec, freqs = got
    return _line_score_at(spec, int(np.argmin(np.abs(freqs - symbol_rate))))


# Bounds on a rate `strongest_line` is allowed to propose. Not statistical -
# they are the range in which the receiver behind this could actually run.
# Above fs/2.5 there are fewer than 2.5 samples per symbol, and `LinearDemod`
# refuses anything under 2 outright; below 256 symbols in the record no loop in
# the chain has enough to settle. A peak outside these is real spectrum and
# still not a symbol rate this stage can use.
_RESCUE_MIN_SPS = 2.5
_RESCUE_MIN_SYMBOLS = 256


def strongest_line(x: np.ndarray, fs: float,
                   family: str) -> tuple[float, float] | None:
    """Where the cyclostationary line actually is: (rate_hz, score).

    `symbol_rate_line` answers "how strong is the line at the rate I was
    given"; this answers "where is the strongest line", off the same statistic
    and the same averaged spectrum. It exists because a stage handed a wrong
    symbol rate had, until 5 Sep, no way to say so: every candidate failed the
    presence screen, the search returned `failed` with `chain_runs = 0`, and
    the evidence that would have fixed it was already in the spectrum the
    screen had just computed and thrown away.

    MEASURED, 5 Sep, on the 252-file corpus: see `reports/s3_rate_rescue.md`.

    This is deliberately NOT a symbol-rate estimator and must not become one.
    It is a fallback consulted only when everything S2 offered has already been
    refused, its output re-enters the same screen as any other candidate, and
    it can propose exactly one rate per family. Estimation is S2's stage and
    this stage does not get to have an opinion until S2's has failed.

    Returns None when there is nothing measurable, or no bin inside the band
    the receiver could run.
    """
    got = _cyclo_spectrum(x, fs, family)
    if got is None:
        return None
    spec, freqs = got

    n = int(np.asarray(x).size)
    lo = max(_RESCUE_MIN_SYMBOLS * fs / max(n, 1), freqs[1] if freqs.size > 1
             else 0.0)
    hi = fs / _RESCUE_MIN_SPS
    if not np.isfinite(lo) or not np.isfinite(hi) or lo >= hi:
        return None

    band = (freqs >= lo) & (freqs <= hi)
    if not np.any(band):
        return None
    idx = np.flatnonzero(band)
    k = int(idx[int(np.argmax(spec[idx]))])
    rate = float(freqs[k])
    if rate <= 0:
        return None
    return rate, _line_score_at(spec, k)


def _psd(x: np.ndarray, fs: float, nperseg: int = 2048):
    n = int(np.clip(max(256, x.size // 8), 16, min(nperseg, x.size)))
    f, p = sps_signal.welch(x, fs=fs, nperseg=n, noverlap=n // 2,
                            return_onesided=False, detrend=False,
                            scaling="density")
    order = np.argsort(f)
    return f[order], np.maximum(p[order], 1e-30)


def carrier_offset(x: np.ndarray, fs: float) -> float:
    """Residual carrier offset in Hz, from the symmetry of the power spectrum.

    Every scheme this project carries transmits a spectrum symmetric about its
    carrier - a root-raised-cosine skirt either side for the linear family, a
    tone bank placed symmetrically for FSK. So the offset is the shift that
    best maps the spectrum onto its own mirror image, found by correlating the
    PSD with its reverse.

    A power-weighted CENTROID was the first version and is the more obvious
    one. It is right for the linear family and wrong for CPFSK, whose spectral
    sidelobes never decay to the noise floor inside the captured band (the same
    property that defeats S1's SNR estimator - see Dheeraj's note in STATUS).
    Measured on a 4-FSK file de-rotated by a known 25 kHz, the centroid read
    10.6 kHz and the symmetry estimator read 24.95 kHz. A correlation is
    insensitive to a symmetric pedestal; a moment is not.

    THE SIGN IS NOT ALWAYS RECOVERABLE, and the caller must not assume it is.
    When a shift pushes part of the occupied band past the edge of the capture,
    the wrapped spectrum has two equally good centres and no measurement on it
    can choose between them. 4-FSK at 4 samples/symbol is the case in this
    corpus: tones at +/-25 and +/-75 kHz in a 200 kHz band, shifted +25 kHz,
    wrap to a set that is genuinely symmetric about -25 kHz. The magnitude
    comes back right and the sign comes back inverted.

    That is why `search.receive_best` treats this number as one more candidate
    to be scored rather than as a correction to apply, and why `cfo = 0` is
    always in the candidate list.

    Returns 0.0 when there is nothing measurable, which the caller must treat
    as absence of evidence - `carrier_alignment` does.
    """
    x = np.asarray(x, dtype=np.complex128).ravel()
    if x.size < 512 or float(np.mean(np.abs(x) ** 2)) <= 1e-20:
        return 0.0
    f, p = _psd(x, fs)
    p = np.maximum(p - np.percentile(p, 10.0), 0.0)
    peak = float(p.max())
    if peak <= 0:
        return 0.0
    p = p / peak
    c = np.correlate(p, p[::-1], mode="full")
    lag = int(np.argmax(c)) - (p.size - 1)
    return float(lag * (f[1] - f[0]) / 2.0)


# --- the checks themselves --------------------------------------------------

def signal_presence(x: np.ndarray, fs: float, symbol_rate: float, family: str,
                    absent_limit: float = LINE_ABSENT_LIMIT,
                    present_limit: float = LINE_PRESENT_LIMIT) -> Check:
    """Is there a signal at the claimed symbol rate?

    This is the check that makes pure noise a `failed` with a reason rather
    than a `low_confidence` shrug. The distinction matters to whoever is
    waiting: 'nothing of this description is here' ends the search, while 'I
    did not lock' invites another hypothesis.

    It is hypothesis-relative on purpose. A presence test that only asked
    'is there energy' would pass on noise; this one asks 'is there a signal
    with the period you told me about', so a wrong symbol rate fails it too -
    which is exactly what the retry loop needs to rank its candidates.

    Three-valued, and the middle value earns its keep: see the note on
    `LINE_ABSENT_LIMIT`. Only a FAIL stops the chain. An `unknown` costs a
    demodulation that may come to nothing, which is the right price for not
    throwing away a weak signal that would have worked.
    """
    if not np.isfinite(symbol_rate) or symbol_rate <= 0:
        return Check("signal_present", UNKNOWN,
                     "no symbol rate supplied, so there is nothing to look for")
    score = symbol_rate_line(x, fs, symbol_rate, family)
    if score >= present_limit:
        return Check("signal_present", PASS,
                     "symbol-rate line %.1fx the local median" % score,
                     value=score, limit=present_limit)
    if score < absent_limit:
        return Check(
            "signal_present", FAIL,
            "no symbol-rate line at %.0f Hz (%.1fx local median, needs %.1fx) "
            "- either nothing is here or the rate is wrong"
            % (symbol_rate, score, absent_limit),
            value=score, limit=absent_limit)
    return Check(
        "signal_present", UNKNOWN,
        "a weak symbol-rate line at %.0f Hz (%.1fx local median, between the "
        "%.1fx that would settle it either way) - carrying on, and letting the "
        "loops decide" % (symbol_rate, score, absent_limit),
        value=score, limit=present_limit)


def carrier_alignment(x: np.ndarray, fs: float, symbol_rate: float,
                      limit: float = CARRIER_OFFSET_LIMIT) -> Check:
    """Is the spectrum still centred after the CFO hypothesis was applied?

    Run on the signal AFTER de-rotation and BEFORE the matched filter, because
    the matched filter is centred at zero and would pull a badly offset
    spectrum back toward the middle, hiding what this check is looking for.

    `value` is the measured offset in Hz. It doubles as the correction, which
    is what `search.receive_best` retries with - but only as another hypothesis
    to be scored, never as a silent fix. Silently correcting S2 would leave the
    bug in S2 with nothing pointing at it.
    """
    if not np.isfinite(symbol_rate) or symbol_rate <= 0:
        return Check("carrier_aligned", UNKNOWN,
                     "no symbol rate supplied, so there is no scale to judge "
                     "an offset against")
    off = carrier_offset(x, fs)
    frac = abs(off) / symbol_rate
    if frac <= limit:
        return Check("carrier_aligned", PASS,
                     "spectrum centred within %.3f of the symbol rate" % frac,
                     value=float(off), limit=limit * symbol_rate)
    return Check(
        "carrier_aligned", FAIL,
        "spectrum sits %+.0f Hz off centre (%.2f of the symbol rate, limit "
        "%.2f) - the carrier offset hypothesis is wrong" % (off, frac, limit),
        value=float(off), limit=limit * symbol_rate)


def output_usable(estimated_ber: float,
                  limit: float = OUTPUT_BER_LIMIT) -> Check:
    """A stage may not claim success while its own quality estimate says it
    failed. See `OUTPUT_BER_LIMIT` for the two files that needed this said out
    loud."""
    if not np.isfinite(estimated_ber):
        return Check("output_usable", UNKNOWN,
                     "the output error estimate is not a finite number")
    if estimated_ber <= limit:
        return Check("output_usable", PASS,
                     "estimated output BER %.3g is inside the %.2g a locked "
                     "receiver should report" % (estimated_ber, limit),
                     value=float(estimated_ber), limit=limit)
    return Check(
        "output_usable", FAIL,
        "the receiver estimates its own output BER at %.3g, over the %.2g a "
        "lock should produce - it is describing a demodulation it cannot claim"
        % (estimated_ber, limit),
        value=float(estimated_ber), limit=limit)


def alphabet_used(symbols: np.ndarray, constellation: np.ndarray,
                  limit: float = ALPHABET_ENTROPY_LIMIT,
                  min_symbols: int = 500) -> Check:
    """Does the received cloud use the whole alphabet this hypothesis claims?

    The only check here that can catch a hypothesis whose constellation
    CONTAINS the transmitted one - see `ALPHABET_ENTROPY_LIMIT` for the
    QPSK-read-as-16-QAM case that reports an estimated bit error rate of
    1.8e-21 against an actual 0.48.

    (The word this paragraph keeps reaching for is banned in this package
    by `test_no_label_lookup_anywhere_in_the_stage`, which greps for it
    case-insensitively. The grep is crude on purpose - a blindness gate
    that needs interpretation is not a gate - so the prose bends, not the
    test.)

    Rotation-invariant, because every rotation a linear scheme is ambiguous
    under maps its constellation onto itself; which of the S rotations reached
    does not change which points were used.
    """
    y = np.asarray(symbols, dtype=np.complex128).ravel()
    pts = np.asarray(constellation, dtype=np.complex128).ravel()
    if y.size < min_symbols or pts.size < 2:
        return Check("alphabet_used", UNKNOWN,
                     "too few symbols to say how the alphabet was used")

    y = y / (np.sqrt(np.mean(np.abs(y) ** 2)) or 1.0)
    pts = pts / (np.sqrt(np.mean(np.abs(pts) ** 2)) or 1.0)
    idx = np.argmin(np.abs(y[:, None] - pts[None, :]), axis=1)
    p = np.bincount(idx, minlength=pts.size).astype(np.float64)
    total = p.sum()
    if total <= 0:
        return Check("alphabet_used", UNKNOWN, "no symbols were assigned")
    p = p / total
    nz = p[p > 0]
    entropy = float(-np.sum(nz * np.log(nz)) / np.log(pts.size))
    used = int(np.count_nonzero(p > 0.2 / pts.size))

    if entropy >= limit:
        return Check("alphabet_used", PASS,
                     "all %d constellation points carry traffic (evenness "
                     "%.3f)" % (pts.size, entropy),
                     value=entropy, limit=limit)
    return Check(
        "alphabet_used", FAIL,
        "only %d of %d constellation points carry traffic (evenness %.3f, "
        "needs %.2f) - this looks like a smaller alphabet seen through a "
        "larger one, which demodulates cleanly and decodes to noise"
        % (used, pts.size, entropy, limit),
        value=entropy, limit=limit)


def tone_alias(cfo_hz: float, tone_spacing_hz: float,
               tolerance: float = 0.15) -> Check:
    """Is the carrier-offset hypothesis one that maps an FSK tone bank onto
    itself?

    The frequency-domain twin of the constellation rotation ambiguity, and the
    `fsk_plugin` docstring claimed for two days that FSK had no such thing. It
    was right about PHASE - energy detection does not care - and wrong about
    frequency. Shift an M-FSK signal by exactly one tone spacing and the set of
    tones is unchanged while every tone's LABEL moves by one, so every symbol
    decodes to its neighbour.

    Measured on `4fsk_13dB_2033`: the search offered a -49 951 Hz correction
    against a 50 kHz tone spacing, the tone bank came back at
    [-0.375, -0.125, 0.125, 0.375] - identical to the true one - and the file
    demodulated at a bit error rate of 0.248, which is exactly what one
    position of slip costs a Gray-labelled 4-ary alphabet. Every other check
    passed, because nothing about the received signal was wrong.

    S3 cannot resolve this from the signal, so it refuses the hypothesis rather
    than guessing between M equally good readings of it.
    """
    if not np.isfinite(cfo_hz) or not np.isfinite(tone_spacing_hz) \
            or tone_spacing_hz <= 0:
        return Check("tone_alias", UNKNOWN,
                     "no measured tone spacing to compare the offset against")
    if abs(cfo_hz) < tolerance * tone_spacing_hz:
        return Check("tone_alias", PASS,
                     "carrier offset is small against the %.0f Hz tone spacing"
                     % tone_spacing_hz, value=float(cfo_hz))
    slip = abs(cfo_hz) / tone_spacing_hz
    nearest = round(slip)
    if nearest >= 1 and abs(slip - nearest) <= tolerance:
        return Check(
            "tone_alias", FAIL,
            "the carrier offset is %.2f tone spacings, which maps the tone "
            "bank onto itself and slips every symbol label by %d - the "
            "hypothesis cannot be told from %d others"
            % (slip, int(nearest), int(nearest)),
            value=float(cfo_hz), limit=float(tone_spacing_hz))
    return Check("tone_alias", PASS,
                 "carrier offset is %.2f tone spacings, not a whole number of "
                 "them" % slip, value=float(cfo_hz))


def loop_check(name: str, converged: bool, detail_ok: str,
               detail_bad: str, value: float | None = None) -> Check:
    """A verdict one of the tracking loops already computed.

    Timing convergence and equaliser convergence were both being measured,
    reported in `values`, and then ignored when the status was decided. Making
    them votes costs nothing and closes two ways of being confidently wrong.
    """
    return Check(name, PASS if converged else FAIL,
                 detail_ok if converged else detail_bad, value=value)
