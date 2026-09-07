# The LDPC decode path, against a supplied parity-check matrix

Owner: Anvith. 7 September, day-clock block C ("LDPC decode path with a
supplied parity-check matrix") and block E ("LDPC decodes with the supplied
H").

**Both blocks are closed.** The decode path is
`pipeline/s3_receive/ldpc_code.py`, registered as `CODES["ldpc"]`, and block
E's four acceptance criteria are tests rather than claims - §5 has the numbers.

**It is in the S3 owner's directory rather than `pipeline/s5_decode/`, where a
`CodePlugin` belongs.** That directory is Nehal's, and the standing rule here
is that a file in someone else's folder is a request at the sync and never an
edit; it has held all week and is why four people on one pipeline have had no
merge conflicts. So the file is written to move - it imports nothing from S3
and reaches the system only through the registry - and §6 is a one-line
relocation request rather than a request to build anything.

Two measurements had to come first, because the plug-in could not be written
without them: **the two things S3 has to supply an LDPC decoder, one of which
S3 was not reporting at all.**

---

## 1. Why this needed measuring at all

Every consumer S3 has today is indifferent to two properties of its output. An
LDPC decoder is indifferent to neither.

| | Viterbi (`conv_code`) | Reed-Solomon (`rs_code`) | S4 rank collapse | **LDPC / BP** |
|---|---|---|---|---|
| needs to know where the stream starts | no | no | no | **yes** |
| needs LLR magnitudes to be truthful | no | no | no | **yes** |

* **Viterbi** maximises a sum of LLRs. Multiply every LLR by any positive
  constant and the arg-max is unchanged, so a uniformly over-confident demapper
  costs it nothing.
* **Reed-Solomon** as this project uses it works on hard symbols: it sees only
  `llr < 0`.
* **S4** hard-slices by construction — rank over GF(2) has no partially
  dependent row — and tolerates an arbitrary start offset, which its per-file
  label JSON has carried as `start_offset` since 29 August.
* **Sum-product belief propagation** has neither indifference. A check node
  combines its inputs through `tanh(L_out/2) = prod_j tanh(L_j/2)`, which is
  neither linear nor scale-free, so magnitudes are load bearing. And a codeword
  has a first bit: a stream whose origin is unknown gives the decoder forty
  thousand candidate alignments instead of one.

So an LDPC path is the first thing in this repo that asks S3 questions nothing
has asked before, and neither answer was on record. Both are now.

---

## 2. Where the stream starts — closed today

### What was wrong

`S3Result.values` did not let a consumer work out which transmitted bit
`llrs[0]` corresponds to. Three of the terms were reported
(`carrier_settled_at`, `equaliser_warmup_dropped`, `bits_per_symbol`) and adding
up everything a consumer could see left it short by a **constant 507 symbols**
— 507 bits on BPSK and 2028 on 16-QAM, the shortfall scaling with bits per
symbol. Not a usable answer to "where does this start", against true offsets
that run from 1107 bits to 20 140.

The missing 507 is three quantities the stage knows and a consumer cannot see:
Gardner's two-symbol interpolator head start, the 500-symbol timing settling
trim, and the equaliser's centre tap at 5 of its 11.

### What S3 reports now

Two new keys in `values`, on both the linear and the FSK branch:

    llr_start_bit             index in the transmitted bit stream of llrs[0]
    llr_start_bit_tolerance   how far out that can be, in bits (= bits/symbol)

Measured against the harness's `align` — which knows, because it holds the
reference bits — over **every modulation at every SNR in the corpus, 36 files**:

| modulation | files | error range (bits) | tolerance | outside tolerance |
|---|---|---|---|---|
| bpsk | 6 | 0 to +1 | 1 | 0 |
| qpsk | 6 | 0 to +2 | 2 | 0 |
| 8psk | 6 | 0 to +3 | 3 | 0 |
| 16qam | 6 | 0 to +4 | 4 | 0 |
| 2fsk | 6 | 0 to +1 | 1 | 0 |
| 4fsk | 6 | 0 to +2 | 2 | 0 |

**36 of 36 inside tolerance, and the residue is never more than one symbol.**
`carrier_settled_at` ranged from 0 to 3328 across those files and the value
tracked it — this is not a constant that happens to fit one cell.

Two properties worth having in writing, because a decoder can use both:

* **The error is never negative.** The true start is at or after
  `llr_start_bit`, on all 36 files. A consumer searches forward only.
* **The residue is a discarded half-symbol, not sloppiness.** Gardner's first
  output sits at sample `2 + 2*period`, which at 4 samples per symbol is
  symbol 2.5; the floor division that turns it into a symbol count throws the
  0.5 away. That is why every observed error is either 0 or exactly one
  symbol - 0 or +1 bit on BPSK, 0 or +4 on 16-QAM - rather than scattered.
  One symbol is the floor here, not a number more care would remove, and
  reporting the value as exact would have been the more useful claim and the
  false one. That is what `llr_start_bit_tolerance` exists to prevent.

### What that leaves for the decoder

An LDPC codeword needs an exact alignment, and one symbol is not exact. But the
search it has to do is now **`bits_per_symbol` + 1 candidate offsets, forward
only** — at most 5 — instead of the length of the stream. That is the
difference between a search nobody would write and one that costs nothing.

FSK needs even less: measured offset 0 to 2 bits, because that branch has no
equaliser, no carrier loop and no settling trim to drop symbols for.

The 36-file table above is the measurement.
`tests/unit/test_s3_ldpc_junction.py::test_reported_llr_start_bit_matches_the_measured_offset`
runs **12 of those 36** as an assertion rather than a report - one file per
modulation at 8 dB and 20 dB, chosen because 8 dB is where
`carrier_settled_at` is non-zero and varies (3328 on the 16-QAM file against 0
on BPSK), so the reported value has to track something rather than happen to
match a constant. The 4 dB files are excluded from the TEST, not from the
measurement: 8-PSK and 16-QAM there come back near 0.42 raw BER, where `align`
itself is barely working, and a test whose instrument is unreliable on the
input is not evidence about what it names.

---

## 3. Whether the magnitudes can be trusted — measured today

Full study and method: **`reports/s3_llr_calibration.md`**, regenerated by
`reports/s3_llr_calibration_study.py`.

`softmap.estimated_ber` already turns the stream into a predicted error rate
using `P(wrong) = 1/(1+exp(|llr|))`, and the 3 Sep contract pins its MEAN
against the measured bit error rate to within a factor of two. That is an
aggregate claim and BP does not consume an aggregate: a demapper that is
over-confident on its strong bits and under-confident on its weak ones has a
correct mean and a useless reliability curve. So the study bins by `|LLR|` and
asks, inside each bin, whether the bits go wrong at the promised rate.

**The answer splits on S3's own `status`, and the split is the finding.**

| population | worst per-bin ratio (empirical / promised) | reading |
|---|---|---|
| files S3 returned `ok` on | **1.62x** (16-QAM 1.25, 4-FSK 1.41, 2-FSK 1.62) | calibrated |
| files S3 refused, `low_confidence` | **81.7x** (16-QAM 4 dB), 65.6x (8-PSK 4 dB) | over-confident |

On a refused file the demapper emits magnitudes of 4 to 8 — promising about
0.4% error — over bits that are wrong 29% and 39% of the time. Those are
exactly the inputs that make sum-product lock onto a wrong codeword and stop.

**So the design rule is: an LDPC decoder gates on `status == "ok"` and never
decodes a refused stream.** Not as a nicety — the refused streams are 50x
outside the band that the decoder's arithmetic assumes.

Inside `ok`, 1.6x is comfortable: it is inside the factor of two the project
already accepts on the aggregate, and sum-product degrades gracefully over that
range. Normalised min-sum would be safer still (below).

**Where this study has no power, stated plainly.** Only three of the six
schemes produced a scorable bin in the `ok` population. BPSK, QPSK and 8-PSK
decode with too few bit errors at every SNR in this corpus to measure a
reliability curve at all — 19 818 of 19 955 BPSK bits at 4 dB sit in the
`|LLR| >= 16` bin with zero errors. Zero errors out of twenty thousand is
consistent with the promise and with a promise ten times smaller. **That is
consistent with calibration and it is not evidence of it**, and the three
schemes are listed as unmeasured rather than as passing.

---

## 4. The plug-in, as built

`pipeline/s3_receive/ldpc_code.py`, registered as `CODES["ldpc"]`. It
satisfies `registry.CodePlugin`, the same shape `ConvCode` and
`ReedSolomonCode` satisfy:

```python
class LDPCCode:
    name = "ldpc"
    def blind_recover(self, llrs) -> None: ...          # always None, see below
    def decode(self, llrs, params: dict) -> np.ndarray: ...
    def validate(self, bits) -> dict: ...
    def syndrome(self, llrs, params: dict) -> dict:     # beyond the protocol
```

### Where it lives, and the thing to fix later

It belongs beside `conv_code.py` and `rs_code.py` in `pipeline/s5_decode/`.
That directory is Nehal's, and the rule this project runs on is that a file in
someone else's folder is a request at the sync and never an edit — the thing
that has kept four people on one pipeline at near-zero merge conflicts all
week. So it sits in the S3 owner's own directory instead, and it is built to
move:

* it imports **nothing** from `pipeline.s3_receive`,
* it reaches the system only through `registry.register_code`,
* every test reaches it by name through `CODES["ldpc"]`, never by import,
* `pipeline/s3_receive/__init__.py` is untouched, so importing S3 does **not**
  register a code plug-in — verified, `CODES` is empty until something asks
  for the module by name.

**Relocating it is `git mv` plus one import line** in
`tests/unit/test_s3_ldpc_junction.py`. Nothing else refers to its path.

### `blind_recover` returns `None`, deliberately

Blind recovery of an LDPC parity-check matrix is on the Command Center's
**Do not build. Ever, this sprint** list (§00), on research grounds: it has no
reliable published method at the error rates a real receiver produces. So
`None` is the specified output rather than a gap. A method that returned a
plausible-looking H it had not recovered would be the confidently-wrong
failure this repo exists to avoid.

### `decode(llrs, params)`

| key | type | meaning |
|---|---|---|
| `H` | `(m, n)` array of 0/1 | dense parity-check matrix |
| `H_rows` | list of lists of int | column indices of the ones in each row |
| `H_alist` | path or text | MacKay alist, the format published matrices ship in |
| `max_iter` | int, default 50 | iteration cap per block |
| `algorithm` | `"min-sum"` (default) or `"sum-product"` | see below |
| `normalisation` | float, default 0.75 | min-sum scale factor |
| `offset` | int | where the first codeword starts, in stream index |
| `search_offsets` | int | how many further offsets to try |
| `k`, `info_positions` | int / sequence | which bits are payload |

**Exactly one of the three H forms**; none and more-than-one both raise. An H
supplied twice by two routes that disagree would decode to a wrong answer with
nothing to report it, and "prefer the first one found" is how that happens
quietly. All three are pinned as describing the same matrix.

**`k` and `info_positions` describe the ENCODER and cannot be derived from H.**
H says which words are codewords; it does not say which of their bits the
sender considered payload. The default — the first `n - m` positions — is the
systematic convention and is right for both fixtures here, but a mismatch
produces a valid codeword and wrong source bits. It is a default said out
loud, not a deduction.

**Normalised min-sum is the default, not sum-product.** Min-sum's check update
is positively homogeneous: scale every input LLR by one positive constant and
the hard decisions do not move. That is immunity to the *scale* half of a
calibration error, which is the half §3 had to go and measure.

**Be precise about what that buys, because it is not "calibration no longer
matters".** It does not remove sensitivity to a *shape* error — a demapper
over-confident on its strong bits and under-confident on its weak ones
distorts the ratios between bins, and no homogeneity argument touches that.
What §3 measured is that the shape error inside the `ok` population is small
(1.06 to 1.62 across bins), so min-sum handles the scale and there is little
shape left for it not to handle. Both algorithms are implemented and both are
pinned by tests; sum-product is one parameter away for the day the calibration
is tighter.

Two implementation notes that are the usual places this goes wrong, both
avoided and both said in the code: the excluding-self combination is computed
**without dividing** by the term being excluded (one zero-magnitude message
would make the row product zero and the division undefined for every edge in
that row), and `sign(0)` is treated as positive rather than zero, which would
otherwise annihilate a whole row's sign product.

**Sign convention: no negation, and it is pinned anyway.** Project LLRs are
`log(P(0)/P(1))`, positive means bit 0, which is the convention textbook BP is
written in — unlike commpy's `viterbi_decode`, where `conv_code.py` has to
negate. "It happens to match" is true until somebody swaps a library, and
getting it backwards decodes to noise and raises nothing.

**Early stop on `H x == 0` over GF(2)**, checked every iteration. A valid
codeword is a valid codeword.

### `validate` and `syndrome`

`validate(bits)` is deliberately weak and the same shape as
`ConvCode.validate` — it catches the degenerate cases (all zeros, all ones)
that mean the decoder locked onto nothing, and claims nothing more.

`syndrome(llrs, params)` is the real check: per-block syndrome weight,
iterations run, and how many blocks converged. **It needs no reference bits**,
which makes it the one check here that a blind receiver can run on its own
output — the same distinction `ConvCode` draws between `validate` and
`validate_against`.

---

## 5. Block E — met, with the numbers

The four things "LDPC decodes with the supplied H" had to show, and what they
measured. All four are tests in `tests/unit/test_s3_ldpc_junction.py`.

**1. A codeword decodes at an SNR where the raw stream does not.** The chain
is: information bits → `ira_encode` → `zoo.rf.through_channel` at 2 dB with a
carrier offset and a fractional timing error → `MODULATIONS["qpsk"].receive` →
`CODES["ldpc"].decode`.

| | |
|---|---|
| S3 status | `ok` |
| raw bit error rate out of the demodulator | **0.0091** |
| source bits wrong after LDPC decoding | **0** |
| blocks reaching a zero syndrome | 5 of 5 |

The SNR is chosen so the raw stream is *not* already correct. At 5 dB and
above it is exact, and a decode that succeeds there demonstrates that the
plumbing runs and nothing else.

**Where it stops working, because a decoder nobody has found the edge of is a
decoder nobody has measured.** On the same code and channel: it still clears a
**6.0%** raw rate at −1 dB, where S3 has dropped to `low_confidence`, and at
−2 dB S3 returns `failed` with no LLRs at all. **On this code the binding
limit is the receiver, not the decoder.** Over a plain AWGN channel with no
receiver in the way it takes 6.5% to zero.

Note that this cuts against §3's design rule in one direction worth stating: a
`low_confidence` stream at 6% raw error decoded perfectly here. The rule to
decode only `status == "ok"` is justified by the 82× over-confident case, not
by every refused stream, so it is conservative and it costs something. It is
the right default and it is not free.

**2. The alignment is found inside the promised window.** The decoder searches
`llr_start_bit_tolerance + 1` offsets — at most five — and finds the codeword
boundary in every run. The direction is what makes it short: `llr_start_bit`
is a *lower* bound, so the boundary computed from it lands at or after the
real one and the search runs backwards by the tolerance.

```python
first = -(-values["llr_start_bit"] // n) * n           # round up to n
base  = first - values["llr_start_bit"] - values["llr_start_bit_tolerance"]
decode(llrs, {"H": H, "offset": base,
              "search_offsets": values["llr_start_bit_tolerance"]})
```

**3. The wrong sign fails, loudly.** Negate every LLR and **0 of 5 blocks**
reach a zero syndrome; the output comes back at a 47% bit error rate. The
syndrome reports it without any reference bits, which is the point — a
sign error is detectable from inside.

**4. `blind_recover` returns `None`** on a zero stream, on noise, and on a
short ramp, and is not wired into anything.

---

## 6. What is still open, and the one request

**The request, to Nehal at the sync:** `git mv pipeline/s3_receive/ldpc_code.py
pipeline/s5_decode/`. It is one move and one import line in the test file; the
plug-in imports nothing from S3 and reaches the system only through the
registry. It is in your directory's remit, so it is yours to say — I put it in
mine rather than write into `s5_decode/` uninvited.

**Two scope facts from the Command Center, checked rather than remembered:**

* Its definition of done for this row is "**both registered** and passing
  through the same chain". Both now are: `MODULATIONS["4fsk"]` and
  `CODES["ldpc"]`, each reached by name.
* The same scope line asks the system to "detect LDPC-like structure when it
  is not [supplied], and say so on screen". **That half is not done and is not
  S3's** — it is structure detection in S4/S6 plus a UI string, and as far as
  this document's author can tell nobody owns it. Worth raising alongside the
  move request.

**Still open, and worth knowing before building on this:**

* **`MIN_SUM_NORMALISATION = 0.75` is inherited, not measured here.** There is
  no corpus of LDPC-coded captures in this project to tune it on. It is the
  middle of the range the literature settles on, labelled as such in the
  constant's own docstring. Choosing a constant on a single arm is the mistake
  the working notes record being punished for twice; this one is not chosen at
  all, which is the honest version until there is something to choose against.
* **Three of six schemes (BPSK, QPSK, 8-PSK) have no measurable calibration
  evidence** in this corpus, because they decode too cleanly to produce
  errors. A corpus with an impairment that costs them real bit errors would
  close it; nothing in `zoo/corpus/rf/` does today.
* The non-coherent FSK LLR still carries a **measured** calibration constant
  of 2.0 rather than a derived one (`softmap._NONCOHERENT_CALIBRATION`).
  2-FSK's 1.62× is the loosest number in the `ok` population and that constant
  is the likely reason.
* **The code used to demonstrate this is a fixture, not a standard.** It is a
  rate-1/2 IRA-style code built in the test file. Nothing here claims a
  CCSDS or DVB-S2 LDPC profile; what it claims is that a supplied H decodes.
