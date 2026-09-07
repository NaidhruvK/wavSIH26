# The LDPC decode path, against a supplied parity-check matrix

Owner: Anvith. 7 September, day-clock block C ("LDPC decode path with a
supplied parity-check matrix") and block E ("LDPC decodes with the supplied
H").

**This is a design and a set of measurements. The plug-in is not written, so
block E does not close today, and the honest statement is that it is open
rather than done.** `pipeline/s5_decode/` is Nehal's, a `CodePlugin` belongs
beside `conv_code.py` and `rs_code.py`, and the standing rule in this project
is that a file in someone else's directory is a request at the sync and never
an edit. It has held for four days and is why four people on one pipeline have
had no merge conflicts. The request is at the bottom of this document, with
everything the implementer needs already measured.

What the day did produce is the part that is mine and that the plug-in cannot
be written without: **the two things S3 has to supply an LDPC decoder, both
measured, one of them missing until this afternoon.**

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

## 4. The plug-in, specified

### Interface

`registry.CodePlugin`, the same shape `ConvCode` and `ReedSolomonCode`
satisfy. Registration is `register_code(LDPCCode())` at the bottom of the file
and nothing else; `pipeline/s5_decode/__init__.py` is empty and stays empty,
because plug-ins self-register on explicit import.

```python
class LDPCCode:
    name = "ldpc"

    def blind_recover(self, llrs) -> dict | None: ...
    def decode(self, llrs, params: dict) -> np.ndarray: ...
    def validate(self, bits) -> dict: ...
```

### `blind_recover` returns `None`, deliberately

Blind recovery of an LDPC parity-check matrix from a soft stream is stated as
out of scope and an open research problem in `reports/envelope.md`, and the
day-clock row says "with a SUPPLIED parity-check matrix". The method must
therefore return `None` rather than a guess. House rule: a check that cannot
see must say so, and a `blind_recover` that returned a plausible-looking H it
had not recovered would be the confidently-wrong failure this repo has been
bitten by repeatedly.

### `decode(llrs, params)`

`params` supplies H. Recommended shape, in the order the plug-in should try:

| key | type | meaning |
|---|---|---|
| `H` | `(m, n)` array of 0/1 | dense parity-check matrix |
| `H_rows` | list of lists of int | column indices of the 1s in each row (sparse; the form BP actually wants) |
| `H_alist` | path or string | MacKay alist, the interchange format most published matrices ship in |
| `max_iter` | int, default 50 | iteration cap |
| `algorithm` | `"min-sum"` \| `"sum-product"` | see below |

Exactly one of the three H forms; raise on none and on more than one rather
than silently preferring one — an H supplied twice and disagreeing is a caller
bug worth surfacing.

**Recommend normalised min-sum as the default, not sum-product.** Min-sum
replaces the `tanh` product with a min-and-sign, and that update is positively
homogeneous: scale every input LLR by the same positive constant and the hard
decisions are unchanged. The normalisation factor (0.75 to 0.8 is the usual
range) recovers most of the gap to sum-product.

**Be precise about what this buys, because it is not "calibration no longer
matters".** Min-sum removes sensitivity to a UNIFORM scale error. It does not
remove sensitivity to a SHAPE error — a demapper over-confident on its strong
bits and under-confident on its weak ones distorts the ratios between bins, and
no homogeneity argument touches that. What §3 measured is that the shape error
inside the `ok` population is small (1.06 to 1.62 across bins), so min-sum
handles the scale and there is little shape left for it not to handle. Buying
that robustness for a fraction of a dB is the right trade; sum-product stays
available for the day the calibration is tighter.

**Sign convention: no negation.** Project LLRs are `log(P(0)/P(1))`, positive
means bit 0, which is the same convention textbook BP is written in — unlike
commpy's `viterbi_decode(decoding_type="unquantized")`, where `conv_code.py`
has to negate. **Pin it with a test anyway.** Getting it backwards decodes to
noise and raises nothing, and "it happens to match" is exactly the kind of
thing that is true until somebody swaps a library.

**Early stop on `H @ x == 0` over GF(2)**, checked every iteration. A valid
codeword is a valid codeword and further iterations cannot improve it.

### `validate(bits)`

Return the syndrome weight and whether it is zero. Unlike a BER this is
computable without reference bits, so it is a real check rather than a
harness-only one.

---

## 5. What block E needs, so the implementer knows when it is done

"LDPC decodes with the supplied H" should show all four:

1. A codeword built from a supplied H, pushed through `zoo.rf.through_channel`
   and `MODULATIONS[...].receive`, decodes to the transmitted information bits
   **exactly** at an SNR where the raw stream does not.
2. The decoder finds its alignment inside the window §2 promises — searching
   forward from `llr_start_bit` by at most `llr_start_bit_tolerance` bits.
3. The wrong sign fails. Negate the LLRs and the decode must fall apart; a test
   that passes either way is testing nothing.
4. `blind_recover` returns `None` and is not quietly wired into anything.

Note (1) is the one that makes the block worth having: a decode that succeeds
at an SNR where the raw stream already decodes has demonstrated only that the
plumbing runs.

---

## 6. The request

**To Nehal, at the sync:** one new file, `pipeline/s5_decode/ldpc_code.py`,
against the spec above. It touches nothing existing — `__init__.py` in that
package is empty and plug-ins self-register on explicit import, so the diff is
a single added file with no edit to `conv_code.py` or `rs_code.py`. Happy to
write it if you would rather it came from this side; it is in your directory,
so it is yours to say.

**What is already done from the S3 side and needs nothing from anyone:**
`llr_start_bit` and `llr_start_bit_tolerance` are reported, measured over all
36 corpus cells and pinned by a test over 12 of them, and the calibration
question is answered for the `ok` population.

**Two scope facts from the Command Center, checked rather than remembered:**

* Its definition of done for this row is "**both registered** and passing
  through the same chain". 4-FSK is registered and passing; LDPC is neither,
  because the file is not written. Half the row is met and half is not, and
  the half that is not is the half the verify line names.
* "Blind LDPC parity-check recovery" is on the **Do not build. Ever, this
  sprint** list (§00), which is why `blind_recover` returning `None` is the
  specified behaviour and not a shortcut. The same scope line also asks the
  system to "detect LDPC-like structure when it is not [supplied], and say so
  on screen" — that is structure detection in S4/S6 and a UI string, not S3,
  and as far as this document's author can tell nobody owns it yet. Worth
  raising at the sync alongside the file request.

**Still open, and worth knowing before building on this:**

* Three of six schemes (BPSK, QPSK, 8-PSK) have no measurable calibration
  evidence in this corpus, because they decode too cleanly to produce errors.
  A corpus with an impairment that costs those schemes real bit errors would
  close it; nothing in `zoo/corpus/rf/` does today.
* The non-coherent FSK LLR still carries a measured calibration constant of
  2.0 rather than a derived one (`softmap._NONCOHERENT_CALIBRATION`). 2-FSK's
  1.62x is the loosest number in the `ok` population and that constant is the
  likely reason.
