"""Stage 3 - the receiver chain. Owner: Anvith.

Every modulation this project supports is a plug-in registered here. Adding one
is a file in this package and a single `register_modulation()` line; nothing in
the orchestrator, the service or the UI names a scheme.

Registered, in the order the plan lands them:

    bpsk, qpsk   31 Aug   LinearDemod through timing and carrier
    2fsk         31 Aug   non-coherent branch
    8psk          1 Sep   one more registration line, no new code
    16qam         2 Sep   MMA equaliser + decision-directed carrier
    4fsk          2 Sep   one registration line - the 2 Sep gate reads "all six
                          modulations", and FSKDemod already generalised on
                          order, so registering it was cheaper than explaining
                          why the registry held five. 7 Sep's 4-FSK row becomes
                          hardening and measurement rather than new code.

The output contract, which S4 and S5 depend on:

    demodulate(iq, params) -> float64 LLR array, log P(0)/P(1), positive = bit 0

`receive()` returns the same LLRs inside an S3Result with the diagnostics
attached. See result.py for why there are two entry points.

4 Sep adds a third, above both:

    receive_best(iq, params) -> S3Result   (search.py)

`receive()` answers "here is what happened when I tried the hypothesis you gave
me". `receive_best()` answers "here is the best I could do across the ranked
hypotheses S2 actually produced", which is a different question and the one an
orchestrator wants. It screens candidates with `lockcheck` before spending a
chain run on them, so trying the whole registry product stays bounded.

Also 4 Sep: `status` is no longer one threshold on one number. `lockcheck.py`
has the measurement that made that necessary.
"""
from __future__ import annotations

from registry import register_modulation

from .base import ModulationPlugin, S2Params
from .bitmap import (bits_per_symbol, bits_to_symbol_indices, label_bit_matrix,
                     symbol_indices_to_bits, symbol_labels)
from .carrier import (CostasResult, constellation, costas_loop, lock_metric,
                      phase_rotation_candidates)
from .cumulants import CUMULANT_KEYS, cumulants
from .equalise import (CMAResult, cma_equalise, dispersion_constants,
                       mma_equalise)
from .filters import (estimate_occupied_band, estimate_rolloff, matched_filter,
                      rrc_taps)
from .fsk import FSKResult, estimate_tones, fsk_demod_noncoherent
from .fsk_plugin import FSKDemod
from .linear import LinearDemod
from .lockcheck import (Check, LockReport, carrier_alignment, carrier_offset,
                        signal_presence, symbol_rate_line)
from .metrics import evm_percent, hard_decisions, magnitude_dispersion
from .result import REQUIRED_VALUES, STATUSES, Hypothesis, S3Result
from .schemes import SCHEMES, Scheme, psk_constellation, scheme
from .search import Candidate, params_from_s2, receive_best
from .softmap import (estimate_noise_variance, estimated_ber, llr_health,
                      llr_to_bits, max_log_llr, noncoherent_llr, windowed_llr)
from .timing import GardnerResult, gardner_sync, smoothed_error

__all__ = [
    "LinearDemod", "FSKDemod", "S2Params", "ModulationPlugin",
    "S3Result", "Hypothesis", "REQUIRED_VALUES", "STATUSES",
    "receive_best", "params_from_s2", "Candidate",
    "LockReport", "Check", "signal_presence", "carrier_alignment",
    "symbol_rate_line", "carrier_offset",
    "Scheme", "SCHEMES", "scheme", "psk_constellation",
    "rrc_taps", "matched_filter", "estimate_rolloff", "estimate_occupied_band",
    "gardner_sync", "GardnerResult", "smoothed_error",
    "costas_loop", "CostasResult", "constellation", "lock_metric",
    "phase_rotation_candidates",
    "cma_equalise", "mma_equalise", "CMAResult", "dispersion_constants",
    "estimate_tones", "fsk_demod_noncoherent", "FSKResult",
    "cumulants", "CUMULANT_KEYS",
    "evm_percent", "hard_decisions", "magnitude_dispersion",
    "max_log_llr", "noncoherent_llr", "estimate_noise_variance",
    "estimated_ber", "llr_to_bits", "llr_health", "windowed_llr",
    "bits_per_symbol", "symbol_labels", "label_bit_matrix",
    "bits_to_symbol_indices", "symbol_indices_to_bits",
    "PLUGINS",
]

PLUGINS = [
    LinearDemod("bpsk"),
    LinearDemod("qpsk"),
    LinearDemod("8psk"),
    LinearDemod("16qam"),
    FSKDemod(2),
    FSKDemod(4),
]

for _p in PLUGINS:
    register_modulation(_p)
