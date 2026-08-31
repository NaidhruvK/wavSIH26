# Stage 4 — the BER ceiling

**Nehal · 29–30 August 2026 · the number the 30 Aug gate asks for**

Regenerate with `python reports/ber_ceiling_study.py`. Outputs
`ber_ceiling.png`, `ber_ceiling.csv`, `ber_study.log`.

---

## Read this before quoting any number below

**The errors here are independent.** They are injected bit flips from the zoo's
bits-only mode. Real demodulator errors are bursty and correlated, because a
carrier or timing loop that slips produces a run of wrong symbols, not a
scattering of them. Every ceiling on this page is therefore an **optimistic
bound**.

The honest version gets measured on **3 September**, when S4 first consumes
real LLRs out of Anvith's S3. That is the number that goes in the envelope
report and the one we say out loud to a judge. This page exists so that on the
3rd we already know what "normal" looks like and can tell degradation from a
bug.

Every metric in `ber_ceiling.csv` is tier `injected`.

## The headline

Ceiling = highest injected BER at which the method succeeded on **every** trial.
Rate 1/2 K=7 (171,133), 60 000 source bits, 8 trials per point for the exact
methods and 5 for the statistical ones.

| Method | What it recovers | Ceiling | Degrades to |
|---|---|---|---|
| Exact rank — code structure | n and m from a raw coded stream | **0 %** | wrong K above 0.05 %, but the guard catches it — see below |
| Exact rank — interleaver period | period of an 8×12 block interleaver | **0.30 %** | 25 % @ 0.5 %, 0 % @ 0.75 % |
| Statistical — blind | span, symbol size n, and the parity check, from nothing | **3.0 %** | 0 % @ 5 % |
| Statistical — tracking | the parity check, span already known | **3.0 %** | 0 % @ 5 % |

**The statistical method is worth roughly 10× the exact one** — 3.0 % against
0.30 % — and that gap is the entire reason both exist. Everything above 0.3 %
BER that Stage 4 will ever decode, it decodes statistically.

Every method fails to *nothing*, never to a wrong answer. Across all 13 error
rates and every trial, no method returned a confidently incorrect parameter.
That is the property that matters more than any ceiling.

## The validator measures the channel too

The syndrome bias is `(1 − 2p)^w` for a check of weight `w`, so inverting it
estimates the channel BER. Measured against truth across 0–3 %:

| Injected | 0.05 % | 0.1 % | 0.2 % | 0.5 % | 1.0 % | 2.0 % | 3.0 % |
|---|---|---|---|---|---|---|---|
| **Inferred** | 0.05 % | 0.11 % | 0.21 % | 0.49 % | 0.98 % | 1.98 % | 2.99 % |

Within 0.02 percentage points everywhere. This is the cheapest credibility
artefact in the project: Stage 4 does not only say what the code is, it says
what the channel was, and that claim is independently checkable.

## Why the exact code readout is the most brittle piece

It requires the measured deficiency to equal `L/n − m` at every deficient row
length. Errors only ever *add* rank, so a single flipped bit anywhere in the
matrix breaks the equality. Measured on a raw coded stream:

| BER | span | n | m | `consistent` | deficiency @ L = 14,16,18,20,22 |
|---|---|---|---|---|---|
| 0 | 14 | 2 | 6 | **True** | 1 2 3 4 5 |
| 0.001 % | 14 | 2 | 6 | **True** | 1 2 3 4 5 |
| 0.005 % | 14 | 2 | 6 | False | 1 2 2 3 4 |
| 0.03 % | 14 | 2 | 6 | False | 1 2 2 3 3 |
| **0.05 %** | **16** | 2 | **7** | False | 0 1 1 2 2 |

Read the last row carefully. At 0.05 % the L = 14 deficiency is erased, the
span estimate slides to 16, and the readout becomes **K = 8 for a K = 7 code**.
The `consistent` flag has been False since 0.005 % — it goes down well before
the answer goes wrong, so that wrong answer never reaches a screen. A guard
that trips early is doing its job; one that trips late is worse than none.

There is an obvious relaxation — errors can only reduce deficiency, so accept
`deficiency(L) ≤ L/n − m` instead of equality. **I did not take it**, because
on the 0.05 % row that relaxed test *passes* with the wrong m = 7. The correct
discriminator is the slope, and tuning a slope threshold against the wrong
error model is work that would have to be redone on the 3rd anyway. It belongs
in the 21 Oct – 20 Nov noise-robustness window, tuned against real bursty
errors. Logged as such.

## What limits the statistical method

Generation, not validation, and the two are very far apart.

- **Generation** draws `span + 6` same-phase windows and takes the null space.
  It only yields the true check when every drawn window is error-free, so the
  hit rate goes as `(1−p)^(20·14)`. That is what dies at ~3 %.
- **Validation** needs only a bias distinguishable from a coin over ~60 000
  windows, and stays significant far beyond 10 %.

So a check is much harder to *find* than to *confirm*. That asymmetry is
exploitable and the plan already has the shape for it: recover the check once
on the cleanest file in a capture, then track it across files far too noisy to
have recovered it from. `statistical_recover(bits, spans=[known_span])` is that
path today.

One implementation note that mattered: drawing `span − 1` windows — the obvious
minimum — is the wrong choice twice over. Only ~29 % of clean draws are
independent enough to give a 1-dimensional null space, and every erroneous draw
still votes for a random vector. Drawing six extra rows raises the clean yield
to 99 % and drops spurious votes from 0.55 to 0.01 per draw at 5 % BER, because
an erroneous system is then almost certainly full rank and votes for nothing at
all. Both effects push the same way.

## The 30 August gate

> PASS = the recovery-vs-BER curve exists and the ceiling is a stated number.

Curve: `reports/ber_ceiling.png`. Raw data: `reports/ber_ceiling.csv`.

**Stated: the exact rank test holds to 0.30 % BER. The statistical
parity-check method holds to 3.0 %. Both against independent injected errors,
which is an optimistic model — the real figure lands on 3 September.**

## Reproducibility, checked rather than assumed

These numbers were first produced on Python 3.13.7 and then regenerated on
3.11.9 after the team standardised (`docs/python-version-decision.md`). Every
metric in `ber_ceiling.csv` came back **byte-identical** across the two
interpreters — including the `implied_ber` floats at full precision. Same for
`rank_profile.csv`.

Wall-clock timing now lives in `ber_ceiling_timing.csv`, not in the metrics
file. It was in the metrics CSV originally, which meant the file could never be
byte-compared and a human had to eyeball the diff instead — which is exactly
how a real change slips past a "numbers identical" check. The 8 Sep gate wants
a comparison a script can make.

## A correction folded into this run

An earlier version of these numbers was produced before a generator bit-order
bug was found by cross-checking our encoder against `commpy` (see
`rank_profile.md`). The whole study was regenerated afterwards. The ceilings
are materially unchanged — reversing a generator polynomial preserves the tap
weights and the rank structure, so neither the collapse profile nor the
syndrome bias moves — but the artefacts in this directory are now the output of
the code that is actually in the tree. Do not mix figures from before that fix
into any document.

## Next

1. Re-run against Dheeraj's real zoo the moment it lands; delete the local
   stand-in the same commit.
2. ~~Wire the statistical validator into `blind_recover`~~ — **done 31 Aug.**
   `blind_recover` now falls back to the statistical search whenever the exact
   test gives up, so the pipeline delivers the 3 % ceiling rather than the
   0.3 % one. Verified end to end at 0.05 %, 0.2 %, 1 % and 3 % BER: correct
   generators every time, inferred BER within 0.0004, `method="statistical"`
   on the result so it is never ambiguous which path produced an answer. The
   fallback carries an 8 s wall clock — the search is worst on inputs that
   contain nothing, which is precisely what gets fed to it deliberately.
3. Re-measure everything on 3 Sep against real LLRs. Expect all four ceilings
   to move down, and expect the *ordering* to survive.
