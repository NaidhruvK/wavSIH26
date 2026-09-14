"""The candidate set `LDPCCode.blind_recover` identifies against.

WHAT CHANGED ON 13 SEP, AND WHAT DID NOT
----------------------------------------
`ldpc_code.py` has said since it was written that blind recovery of H is out of
scope, on research grounds, and returned None rather than a plausible-looking
matrix it had not recovered. That judgement stands and is not weakened here.
What it was answering, though, is the OPEN problem:

    open-set:   recover an arbitrary unknown H from a noisy stream.
                No reliable published method at real receiver error rates.
                Still refused. `blind_recover` still returns None for it.

    closed-set: decide WHICH H, out of a known finite catalogue, a stream was
                encoded with - and where its codewords start.
                Tractable, decisive, and what this file adds.

Those are different problems and conflating them cost the project a deliverable.
The second is not a weaker version of the first; it is the one a SIGINT receiver
actually faces, because a downlink is overwhelmingly likely to be using a
published code rather than a bespoke one, and it is the same shape as two
closed-set searches this repo already trusted: the CCSDS symbol interleaver's
six legal depths, settled by whether RS decodes, and the LTE QPP table in
`s4_recover/pseudorandom.py`. Both are "the standard has a short list, try the
list". So is this.

HOW THE DECISION IS MADE: SYNDROME DENSITY, NOT A DECODE
--------------------------------------------------------
For a candidate (H, offset), slice the hard-decided stream into n-bit blocks and
count how many parity checks fail. Two populations, and they do not overlap:

  wrong H, or right H at the wrong offset
      the bits are effectively random with respect to every row of H, so each
      check fails independently with probability 1/2. Over N = m*blocks checks
      the failure count is Binomial(N, 1/2): mean 0.5N, sd 0.5*sqrt(N).

  right H at the right offset, at bit error rate eps and row weight w
      a check fails only on an odd number of errors among its w bits,
          P(fail) = (1 - (1 - 2*eps)^w) / 2
      which is 0 at eps = 0 and 0.057 at eps = 1%, w = 6.

So the statistic is z = sqrt(N) * (1 - 2*p_hat) - how many standard deviations
below coin-flipping the observed failure rate sits. When p_hat is exactly zero z
is exactly sqrt(N), so the true-code score is set by how many checks the capture
supplies and grows without bound with capture length. Measured across all seven
shipped entries at MIN_ID_BLOCKS = 6 blocks, no channel errors, codeword start
shifted by 37 bits so the offset search has to find it:

    entry                      N checks   p_hat   z        offset
    reference-n48                   144   0.000   +12.0    found
    gallager-n96 (both)             288   0.000   +17.0    found
    reference-n96                   288   0.000   +17.0    found
    reference-n192                  576   0.000   +24.0    found
    wimax-802.16e-n960-r3/4        1440   0.000   +37.9    found
    wimax-802.16e-n1440-r1/2       4320   0.000   +65.7    found

    right H, offset wrong by 5 bits       0.545    -1.5
    worst WRONG entry, any stream, any offset       +3.0
    200 random streams vs the n=48 entry  mean +2.2, max +3.7

7 of 7 identified, exact code and exact offset. The gap the decision sits in is
+3.7 (worst null) to +12.0 (weakest true), and identification cost 0.00-0.23 s
per stream against a 15 s stage budget. Under independent bit errors the n=96
Gallager code is still identified at 5% (z = +8.6) and refused at 8%.

This is BP-free and that is the point: belief propagation against a wrong H does
not politely fail, it converges to a wrong codeword and reports a zero syndrome
for it - which is the confidently-wrong failure this repo keeps getting bitten
by. Counting failed checks on the hard decisions cannot do that, because it
never changes a bit.

WHY THE NULL SITS AT +2.2 RATHER THAN 0, AND WHY THAT IS NOT A BUG
-----------------------------------------------------------------
The offset search reports the BEST of n alignments, so the statistic is a
maximum of n correlated draws rather than one draw, and its null distribution is
shifted upward by that order statistic. The nominal Binomial tail therefore
understates the false-positive rate and must not be quoted as if it were the
real one. The empirical null above is what ID_Z_MIN is set against.

THE FALSE POSITIVE THAT MATTERS, AND WHY THE GUARD READS THE INPUT
------------------------------------------------------------------
An all-zero stream satisfies every parity check of every H at every offset -
the zero word is in every linear code. So a degenerate input scores a PERFECT
z against the entire catalogue simultaneously, and no amount of margin between
candidates can reject it, because they all tie at the ceiling. Nothing
downstream can catch this either: the decode is exactly right, for the zero
codeword, and its syndrome really is zero.

Hence `_degenerate_reason`, which reads the BITS and not any score. It is the
same guard `rank_collapse.exact_repetition_period` applies for the same reason,
and it is here rather than in the scoring loop because a guard that lives
inside one branch is not a guarantee.

THE CATALOGUE IS A DIRECTORY, WHICH IS THE HONEST PART
------------------------------------------------------
Identification is closed-set: it finds a code IF THE CODE IS IN THE CATALOGUE,
and says so plainly when nothing matches. Extending it is dropping an alist
file into `registry/ldpc_catalogue/` - no code change, no registration line,
because `load_catalogue` reads the directory.

What ships:

  wimax-802.16e-n1440-r1/2   published 802.16e QC-LDPC, from commpy's designs
  wimax-802.16e-n960-r3/4    published 802.16e QC-LDPC, from commpy's designs
  gallager-n96-r1/2-963      MacKay's (3,6)-regular archive code
  gallager-n96-r1/2-964      MacKay's (3,6)-regular archive code

Those four are read from `commpy.channelcoding.designs` when commpy is
installed, and they are real published matrices rather than anything we made
up. They are also the whole of it, and the gap is named rather than papered
over: CCSDS 231.1-O-1, DVB-S2 and 802.11n are NOT in the catalogue, because
this project has no verified copy of their parity-check matrices and
transcribing one from a standard we cannot check against would put an
unmeasured number into a report. A stream using one of those is reported as
"no catalogue match", which is true, instead of matched to the nearest thing
that happens to be present, which would not be.

`build_reference_catalogue` writes reproducible (3,6)-regular constructions to
the directory so the identification path can be measured at block lengths the
commpy designs do not cover. Those files are labelled `reference-*` and are
OURS, not a standard's - the labelling is load-bearing, because a report naming
the matched code is only useful if the name is true.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger("raaya.ldpc_catalogue")

__all__ = [
    "CatalogueEntry", "load_catalogue", "catalogue_dir", "clear_cache",
    "write_alist", "build_reference_catalogue", "codewords_from_h",
]


def catalogue_dir() -> Path:
    """`registry/ldpc_catalogue/` beside the repo root. Created on demand."""
    return Path(__file__).resolve().parents[2] / "registry" / "ldpc_catalogue"


@dataclass(frozen=True)
class CatalogueEntry:
    """One candidate code.

    `provenance` is not decoration. It travels into the report as the name of
    the matched code, so "802.16e" and "a construction we generated to test
    with" must not be spellable the same way.
    """
    name: str
    h: np.ndarray
    provenance: str

    @property
    def n(self) -> int:
        return int(self.h.shape[1])

    @property
    def m(self) -> int:
        return int(self.h.shape[0])

    @property
    def k(self) -> int:
        """Nominal dimension n - m. Nominal because H may not be full rank;
        the true k is n - rank(H), and nothing here needs it."""
        return self.n - self.m

    @property
    def rate(self) -> float:
        return 1.0 - self.m / self.n

    def as_params(self) -> dict:
        return {"H": self.h, "code_name": self.name,
                "provenance": self.provenance}


_CACHE: list[CatalogueEntry] | None = None


def clear_cache() -> None:
    """Drop the memoised catalogue. For tests that write to the directory."""
    global _CACHE
    _CACHE = None


def _commpy_designs() -> list[tuple[str, Path, str]]:
    """(name, path, provenance) for the published designs commpy ships.

    Located through the installed package rather than by a hard-coded path, so
    it works in the Docker image and in a virtualenv without either being
    special-cased. Returns empty when commpy is absent - the catalogue is then
    whatever is on disk, which is a smaller search and not an error.
    """
    try:
        import commpy.channelcoding as cc
    except Exception as exc:                      # pragma: no cover - env dependent
        logger.debug("commpy designs unavailable: %s", exc)
        return []
    root = Path(cc.__file__).resolve().parent / "designs" / "ldpc"
    known = [
        ("wimax-802.16e-n1440-r1_2", root / "wimax" / "1440.720.txt",
         "IEEE 802.16e (WiMAX) QC-LDPC, via commpy designs"),
        ("wimax-802.16e-n960-r3_4", root / "wimax" / "960.720.a.txt",
         "IEEE 802.16e (WiMAX) QC-LDPC, via commpy designs"),
        ("gallager-n96-r1_2-963", root / "gallager" / "96.3.963.txt",
         "MacKay archive (3,6)-regular Gallager code, via commpy designs"),
        ("gallager-n96-r1_2-964", root / "gallager" / "96.33.964.txt",
         "MacKay archive (3,6)-regular Gallager code, via commpy designs"),
    ]
    return [(nm, p, prov) for nm, p, prov in known if p.is_file()]


def load_catalogue(extra_dirs=None, include_commpy: bool = True
                   ) -> list[CatalogueEntry]:
    """Every candidate code, smallest n first. Memoised.

    Smallest first is deliberate and it is about evidence, not speed. A short
    block gives the offset search fewer positions to be wrong in and needs
    fewer received bits to reach a decisive z, so if two catalogue entries both
    match a stream - which happens when one code's H rows are a subset of
    another's, or when a stream is long enough to satisfy both - the shorter
    one is the weaker claim and the right one to prefer.
    """
    global _CACHE
    if _CACHE is not None and extra_dirs is None and include_commpy:
        return _CACHE

    from .ldpc_code import read_alist

    entries: list[CatalogueEntry] = []
    seen: set[bytes] = set()

    def _add(name: str, h: np.ndarray, provenance: str) -> None:
        if h.ndim != 2 or h.shape[0] >= h.shape[1]:
            logger.warning("catalogue entry %r rejected: H is %s", name, h.shape)
            return
        # Two files carrying the same matrix is a duplicate, not two
        # candidates. It would otherwise split the margin test between two
        # identical winners and make a decisive match look ambiguous.
        key = np.ascontiguousarray(h, dtype=np.uint8).tobytes()
        if key in seen:
            return
        seen.add(key)
        entries.append(CatalogueEntry(name=name, h=np.ascontiguousarray(h, dtype=np.uint8),
                                      provenance=provenance))

    dirs = [catalogue_dir()]
    if extra_dirs:
        dirs.extend(Path(d) for d in extra_dirs)
    for d in dirs:
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.alist")):
            try:
                _add(path.stem, read_alist(path), "%s (catalogue directory)" % path.name)
            except Exception as exc:
                # One malformed file must not take the catalogue down: the
                # directory is a user extension point, so a bad drop is an
                # expected event rather than a bug.
                logger.warning("catalogue file %s skipped: %s", path, exc)

    if include_commpy:
        for name, path, provenance in _commpy_designs():
            try:
                _add(name, read_alist(path), provenance)
            except Exception as exc:              # pragma: no cover - env dependent
                logger.warning("commpy design %s skipped: %s", path, exc)

    entries.sort(key=lambda e: (e.n, e.m, e.name))
    if extra_dirs is None and include_commpy:
        _CACHE = entries
    return entries


# ---------------------------------------------------------------------------
# writing the directory, and generating codewords to measure against
# ---------------------------------------------------------------------------

def write_alist(h: np.ndarray, path) -> Path:
    """Write H in MacKay alist form, the format `read_alist` reads.

    Round-trips through `read_alist` by construction: both sections are
    emitted, and the column section - the one `read_alist` actually parses - is
    written first-index-first with zero padding to the maximum column weight.
    """
    h = np.asarray(h, dtype=np.uint8)
    m, n = h.shape
    col_w = h.sum(axis=0).astype(int)
    row_w = h.sum(axis=1).astype(int)
    lines = ["%d %d" % (n, m), "%d %d" % (int(col_w.max()), int(row_w.max())),
             " ".join(str(int(v)) for v in col_w),
             " ".join(str(int(v)) for v in row_w)]
    pad_c, pad_r = int(col_w.max()), int(row_w.max())
    for c in range(n):
        rows = (np.flatnonzero(h[:, c]) + 1).tolist()
        lines.append(" ".join(str(v) for v in rows + [0] * (pad_c - len(rows))))
    for r in range(m):
        cols = (np.flatnonzero(h[r, :]) + 1).tolist()
        lines.append(" ".join(str(v) for v in cols + [0] * (pad_r - len(cols))))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def regular_ldpc(n: int, col_weight: int = 3, row_weight: int = 6,
                 seed: int = 0) -> np.ndarray:
    """A (col_weight, row_weight)-regular H by seeded permutation stacking.

    Gallager's own construction: stack `col_weight` block rows, each a random
    permutation of a base block that places one 1 per column and `row_weight`
    per row. Reproducible from `seed`, which is what makes it a catalogue entry
    rather than a random matrix - an entry whose H depends on numpy's global
    state is not an entry, it is a different code every import.

    NOT a standard's code and named accordingly by
    `build_reference_catalogue`. It exists so the identification path can be
    measured at block lengths the published designs do not cover.
    """
    if n % row_weight:
        raise ValueError("n=%d must be a multiple of row_weight=%d" % (n, row_weight))
    rows_per_block = n // row_weight
    # SEEDED ON n AS WELL AS `seed`, AND NO IDENTITY BLOCK ROW. Both matter, and
    # the second was a real false positive found on 13 Sep.
    #
    # The first block row used to be `order = arange(n)`, i.e. columns grouped
    # 0..5, 6..11, ... - which is Gallager's textbook illustration and is also
    # IDENTICAL across every n. So reference-n96 and reference-n192 shared that
    # whole block row, the n=192 code's first 96 columns carried the n=96 code's
    # checks, and a genuine n=192 codeword stream scored z = +7.54 against the
    # WRONG n=96 matrix - against a threshold of 8.0, a margin of 0.46.
    #
    # Nested catalogue entries are the realistic version of this: a catalogue
    # grown by adding lengths of one construction will contain related codes,
    # and a scoring rule that only compares against a fixed threshold cannot
    # tell "this is the code" from "this is a code that contains it". So there
    # are two fixes and both shipped: the construction no longer nests, and
    # `blind_recover` now requires a margin over the runner-up rather than
    # trusting the threshold alone. The second is the one that generalises - it
    # holds for catalogue entries this function did not generate.
    rng = np.random.default_rng((int(seed), int(n), int(col_weight), int(row_weight)))
    blocks = []
    for _ in range(col_weight):
        base = np.zeros((rows_per_block, n), dtype=np.uint8)
        order = rng.permutation(n)
        for r in range(rows_per_block):
            base[r, order[r * row_weight:(r + 1) * row_weight]] = 1
        blocks.append(base)
    return np.vstack(blocks)


def build_reference_catalogue(lengths=(48, 96, 192), seed: int = 0,
                              directory=None) -> list[Path]:
    """Write the `reference-*` entries. Idempotent; skips files that exist.

    Called by tests and by `python -m pipeline.s5_decode.ldpc_catalogue`. Not
    called at import: a module that writes to the repo when you import it is a
    surprise, and the catalogue loader is perfectly happy with an empty
    directory.
    """
    out = []
    target = Path(directory) if directory is not None else catalogue_dir()
    for n in lengths:
        path = target / ("reference-n%d-r1_2-regular36-seed%d.alist" % (n, seed))
        if not path.exists():
            write_alist(regular_ldpc(n, 3, 6, seed=seed), path)
        out.append(path)
    clear_cache()
    return out


def codewords_from_h(h: np.ndarray, n_blocks: int, seed: int = 0
                     ) -> tuple[np.ndarray, np.ndarray]:
    """(bitstream, generator) - random codewords of the code H defines.

    Used to MEASURE identification, so it must produce genuine codewords rather
    than something that merely looks like them: the generator is the GF(2) null
    space of H, and the returned stream is asserted to have zero syndrome
    before it is handed back. A test fixture that silently emits non-codewords
    would make the identifier look broken.
    """
    from pipeline.s4_recover.gf2 import null_space_gf2

    h = np.asarray(h, dtype=np.uint8)
    g = null_space_gf2(h)                     # rows span the code
    if g.size == 0:
        raise ValueError("H has a trivial null space - no codewords to draw")
    rng = np.random.default_rng(seed)
    info = rng.integers(0, 2, (n_blocks, g.shape[0]), dtype=np.uint8)
    words = (info @ g) % 2
    if ((h @ words.T) % 2).any():
        raise AssertionError("generator does not span the null space of H")
    return words.astype(np.uint8).ravel(), g


if __name__ == "__main__":                      # pragma: no cover
    written = build_reference_catalogue()
    for p in written:
        print(p)
    for e in load_catalogue():
        print("%-34s H=%4dx%-5d rate=%.3f  %s" % (e.name, e.m, e.n, e.rate,
                                                  e.provenance))
