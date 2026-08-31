# What S4 needs from the zoo's bits-only mode

**Nehal → Dheeraj · written 29 Aug 2026, for the 09:00 sync on the 30th**

This is the one handoff S4 actually blocks on, and per the plan it is what lets
me characterise the BER ceiling nine days before Anvith's demodulator would
otherwise unblock me. I have been running against a local stand-in
(`tests/fixtures/local_zoo.py`) to get the day-one gate green — **that file
gets deleted the moment yours lands.** Two sources of ground truth must not
coexist, because the first time they disagree nobody will know which is right.

Everything below is already implemented in my stand-in, so if it is easier,
lift the generation logic from there wholesale and move it into `zoo/` under
your ownership.

## The stream

Raw coded bits, `uint8` 0/1, no modulation and no pulse shaping. Either a
`.npy` array or a packed binary file — say which and I will read it; I do not
care as long as it is one of the two and consistent.

Pipeline order matters and must match what a real transmitter does:

```
source bits → convolutional encode → interleave → scramble → inject errors
```

Getting scramble and interleave the wrong way round changes the rank signature
entirely, so please state the order in the truth JSON as well as implementing
it.

## Length

**Not negotiable, and the thing most likely to go wrong.** A rank measurement
needs comfortably more rows than columns, so the largest interleaver period
searchable in a stream of `N` bits is roughly `√N`. Concretely:

| Interleaver period | Minimum coded bits |
|---|---|
| 64 | 8 200 |
| 128 | 24 600 |
| 256 | 82 000 |
| 512 | 295 000 |

A stream shorter than this does not produce a wrong answer — it produces "no
code structure detected", which is worse, because it looks like a finding.
Please emit **≥ 150 000 coded bits** per bits-only file so anything up to
period 350 is reachable, and note the length in the truth JSON.

## The truth JSON, one per file

```json
{
  "n_source_bits":   60000,
  "code":            {"family": "conv", "rate": "1/2", "K": 7,
                      "polys_octal": [121, 91], "poly_notation": "octal"},
  "interleaver":     {"family": "block", "depth": 8, "width": 12, "period": 96},
  "scrambler":       {"family": "lfsr", "poly_octal": 127, "seed_state": 127},
  "injected_ber":    0.002,
  "n_flipped":       320,
  "error_model":     "independent",
  "start_offset":    0,
  "pipeline_order":  ["encode", "interleave", "scramble", "inject"],
  "seed":            42
}
```

Two fields that matter more than they look:

- **`poly_notation`** — spell out whether `polys_octal` is octal or decimal.
  This convention (risk #10 in the register) cost me a real bug tonight: the
  wrong bit order produces a parity check that fails on ~50 % of windows, which
  looks like noise rather than like a mistake. If the JSON is explicit, nobody
  else loses time to it.
- **`error_model`** — say `"independent"` explicitly. Every ceiling I measure
  against injected errors is an optimistic bound, and having the model named in
  the data stops an optimistic number being quoted as a real one three days
  from now when everyone is tired.

## Knobs I need to sweep

- `ber` — continuous, **seeded and repeatable**. A trial that fails must be
  reproducible from its seed alone.
- `depth` × `width` — several factorisations, including two with the *same*
  period (e.g. 8×12 and 16×6). Same rank profile, different answer; it is what
  proves the factorisation search works rather than the period search.
- `scramble` on/off — I need the off case until Berlekamp–Massey lands on 7 Sep.
- An **uncoded random** file of the same length. This is the false-positive
  case (risk #15) and a judge will run it. I want it in the corpus, labelled,
  not improvised on the day.

## Ideal, not required

A `start_offset` that is deliberately *not* a block boundary. Recovering the
alignment is part of the problem and my gate already tests it with a random
trim — but corpus files that start mid-block would exercise it end to end.

## What you get back

For every bits-only file, S4 returns period, block alignment, depth×width,
rate, constraint length, and the recovered generator polynomials — plus a
`status` and a `reason` when it declines. Wire it into the coverage matrix
whenever you take over the eval harness on the 3rd.
