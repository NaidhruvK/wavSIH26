# The LDPC decode path, against a supplied parity-check matrix

Owner: Anvith. 7 September, day-clock block C ("LDPC decode path with a
supplied parity-check matrix") and block E ("LDPC decodes with the supplied
H").

**Both blocks are closed.** The decode path is
`pipeline/s5_decode/ldpc_code.py`, registered as `CODES["ldpc"]`, and block E's
four acceptance criteria are tests rather than claims - §5 has the numbers.

It spent its first afternoon in `pipeline/s3_receive/` and moved once the
ownership was agreed, because a `CodePlugin` belongs beside `conv_code.py` and
`rs_code.py` rather than inside the receiver stage. The properties that made
the move cheap were designed in and are worth keeping: it imports nothing from
S3, it touches no existing file, and every test reaches it by name through
`CODES`.

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

`pipeline/s5_decode/ldpc_code.py`, registered as `CODES["ldpc"]`. It
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

### Where it lives

Beside `conv_code.py` and `rs_code.py`, which is Nehal's directory. Written by
the S3 owner because the row is on his day-clock column, and landed there with
agreement rather than dropped in - it sat in `pipeline/s3_receive/` for an
afternoon first, because a file in someone else's folder is a request at the
sync and never an edit.

The isolation that made that move a `git mv` is still true and still useful:

* it imports **nothing** from `pipeline.s3_receive` - only numpy and the
  registry,
* it touches no existing file: `pipeline/s5_decode/__init__.py` is empty and
  stays empty, because code plug-ins register on **explicit** import,
* every test reaches it by name through `CODES["ldpc"]`, never by import.

So rewriting, renaming or replacing it costs one line.

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

## 6. What is still open

**Nothing is blocked on anyone.** The file is in `pipeline/s5_decode/` where it
belongs, both blocks are closed, and the row's definition of done - "**both
registered** and passing through the same chain" - is met by
`MODULATIONS["4fsk"]` and `CODES["ldpc"]`, each reached by name.

**One scope fact from the Command Center, checked rather than remembered.** The
same line that puts "LDPC decoding when the parity-check matrix is supplied" in
scope also asks the system to "detect LDPC-like structure when it is not
[supplied], and say so on screen". **That half is not done and it is not
S3's** - it is structure detection in S4/S6 plus a UI string, and as far as
this document's author can tell nobody owns it. Worth raising at the sync; it
is a visible thing for a judge to ask about.

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
  2-FSK's 1.62x is the loosest number in the `ok` population and that constant
  is the likely reason.
* **The code used to demonstrate this is a fixture, not a standard.** It is a
  rate-1/2 IRA-style code built in the test file. Nothing here claims a CCSDS
  or DVB-S2 LDPC profile; what it claims is that a supplied H decodes.

---

## 7. Is LDPC reachable through the API? No — and that is a decision

Added 8 Sep, answering Nehal's question against `service/orchestrator.py:909`
directly, so that nobody files it as a bug in a week. Everything below was
checked on `origin/main` at `4d25434`, not remembered.

### The short answer

**Nothing supplies H on the service path, and nothing is designed to. LDPC is
reachable only from Python — by name through `CODES["ldpc"]`, or by injecting a
decoder through `orchestrate(..., stage_overrides={"s5_decode": ...})`. It is
not reachable over HTTP, and it is not reachable from the CLI either.**

That last clause is the one correction to the framing of the question. "CLI or
test-only" gives the CLI too much credit: `service/cli.py:109` calls
`orchestrate` with `run_id`, `file_path`, `fs_hint` and `mod_scheme_hint` and
**no `stage_overrides`**, so `analyze` reaches exactly the same hardcoded
`CODES.get("conv")` the HTTP path does. The accurate statement is
**in-process-Python-only**: the unit tests, and any caller who already holds an
H and is willing to write four lines against `orchestrate`.

### Line 909 is the visible half, not the binding one

Fixing `CODES.get("conv")` to iterate `CODES` would **not** make LDPC reachable.
Verified on the merged tree:

```
CODES        ['conv', 'ldpc', 'reed-solomon']     <- Nehal's loader fix works
ldpc.blind_recover(<any llrs>)  -> None           <- by design, see §4
ldpc.decode(llrs, {})           -> ValueError: no parity-check matrix supplied
```

So a dispatch loop that reached the LDPC plug-in would get `None` from
`blind_recover` and a `ValueError` from `decode`, on every input, forever. The
failure would move from "never dispatched" to "dispatched and declined" — which
looks identical from the outside and is *harder* to debug, because it now
appears to be a decoder that tried and failed rather than a path that was never
wired.

**The binding constraint is transport, and there is no transport.** Grepping
`service/`, `contracts/` and `web/` for `H`, `H_rows`, `H_alist`, `parity` and
`alist` returns exactly one hit — `parity_taps` in `adapt_s4`, which is
convolutional parity taps and unrelated. The upload endpoint
(`service/main.py:321`) accepts `file`, `fs_hint` and `mod_scheme_hint`, full
stop. There is no field, form part, query parameter or config key on any route
by which a parity-check matrix can enter the service.

Two halves, and the order matters: **a dispatch that can select a code plug-in,
and a transport that can carry that plug-in's parameters.** Doing the first
alone produces a decoder that is dispatched to and always declines.

### Why it should stay this way through the freeze

This is a judgement, so it is stated as one and the reasoning is on the table:

1. **There is no H to supply.** The judge uploads a WAV. Nothing in the demo
   flow, the corpus or the CCSDS files carries a parity-check matrix, so the
   feature would have no input even if it were wired.
2. **Blind recovery is the only thing that would give it one, and it is on the
   Command Center's *do not build, ever, this sprint* list** (§00) on research
   grounds. `blind_recover` returning `None` is that decision honoured, not a
   gap in it — see §4.
3. **The transport is new file-parsing surface, 24 hours before a freeze.** An
   alist upload means parsing a caller-supplied matrix format on a public
   route, on 8 September, for a case no judge will exercise. That is the worst
   possible trade against the 9 Sep hardening column.

So: **deliberately unreachable through the API, and it should ship that way.**
It is a decoder held ready for an input the service has no way to receive.

### What would have to be true to change it

Written down so this is a decision with a price rather than an oversight. All
three, in order:

1. **A transport.** A field on `/upload` (or a config key) carrying a dense H,
   per-row column indices, or a MacKay alist — the three forms
   `parity_check_from_params` already accepts. It validates and raises on
   ambiguity today, so the plug-in end is done.
2. **A dispatch that selects a code plug-in** rather than naming one, and
   passes that plug-in's own parameters through. Note this is genuinely harder
   than S3's equivalent: house rule 5 ("never name a scheme in orchestration
   code") is enforced on S3 by `test_search_never_names_a_scheme` walking the
   AST, and S3 can get away with a blind iterate-and-try because every
   modulation plug-in takes the *same* parameters. The code plug-ins do not —
   conv wants generators and a rate, RS wants a symbol size, LDPC wants an H —
   so `CODES.get("conv")` is not simply rule 5 being broken. **It is Nehal's
   and Naidhruv's call how that seam should look, and this document is not
   asking for it to change.** What it does ask is that whoever changes it knows
   line 909 has to move at the same time as the transport, or the result is a
   silent decline.
3. **A guard that only decodes `status == "ok"` streams.** Non-negotiable and
   measured: on a stream S3 refuses, the demodulator emits magnitudes of 4–8
   — promising ~0.4% error — over bits that are wrong 29–39% of the time
   (§3, worst per-bin ratio 81.7x against 1.62x on the `ok` population). Those
   are exactly the inputs that make belief propagation settle on a wrong
   codeword and stop, which is a confident wrong answer rather than a failure.
   The plug-in cannot enforce this itself — it never sees an `S3Result`.

### What was actually broken, and is now fixed

For the record, because the two are easy to confuse and only one was a defect:

* **`REQUIRED_PLUGIN_MODULES` did not list `pipeline.s5_decode.ldpc_code`**, so
  the service came up with `CODES = {conv, reed-solomon}` while the plug-in's
  own unit tests stayed green. That was real, it was invisible from both sides,
  and Nehal fixed it plus added a test that scans `pipeline/` for top-level
  `register_*()` calls so a future file move fails loudly. Confirmed here:
  `CODES` now reads `['conv', 'ldpc', 'reed-solomon']` through
  `service.orchestrator.load_plugins()`. **The cause was a file move at 14:43
  against a loader written at 11:14** — a missing plug-in and a scheme nobody
  tried are indistinguishable from the API, which is what made it survive.
* **`CODES.get("conv")` at line 909 is not a bug**, given the above. It is the
  correct dispatch for the only code the service can currently be given the
  parameters for.
