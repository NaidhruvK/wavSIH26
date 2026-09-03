"""Plotting harness for the receiver chain.

29 Aug, Block A: an eye-diagram harness, built before the thing it inspects.
29 Aug, Block D: the constellation plot.

These are diagnostics, not the product. The Plotly panels in the UI are
Naidhruv's and are fed from artifacts; these are Matplotlib PNGs written beside
the evidence for a gate, so a claim in a report has a picture under it.

The eye is the one that matters. A timing loop that has settled onto the wrong
stable point produces a perfectly steady error trace and a closed eye, and the
error trace alone will not tell you which one you have.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .timing import smoothed_error  # noqa: E402

__all__ = ["eye_diagram", "constellation_plot", "timing_trace", "cma_trace",
           "chain_summary"]

_DPI = 110


def _save(fig, path: str | Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def eye_diagram(x: np.ndarray, sps: float, path: str | Path, *,
                spans: int = 2, traces: int = 400, title: str = "Eye diagram",
                skip: int = 200, align_sample: float | None = None) -> str:
    """Overlay `traces` windows of `spans` symbols on one axis.

    align_sample is the recovered decision instant, in samples, from the timing
    loop. Without it the window phase is arbitrary and the eye is drawn opening
    wherever the slice happened to land - which looks like a broken receiver
    even when the loop is perfect. The whole value of an eye is that t=0 is the
    instant the receiver actually samples at, so it must be told where that is.

    Drawn on the real part only. The imaginary part is a second eye, but an
    unlocked carrier smears both, so one axis is enough to read timing quality
    and two just doubles the ink.
    """
    x = np.asarray(x)
    n = int(round(sps * spans))
    start = int(skip * sps)
    frac = 0.0
    if align_sample is not None:
        phase = float(align_sample) % float(sps)
        start = max(start + int(phase) - n // 2, 0)
        frac = phase - int(phase)
    usable = (x.size - start - 2) // n
    if usable < 2:
        raise ValueError("record too short to draw an eye")
    take = min(traces, usable)
    if frac:
        # the decision instant sits between samples; interpolate onto it rather
        # than rounding, which at 4 sps would misplace the eye by an eighth of a
        # symbol and make a locked loop look mistimed
        grid = np.arange(start, start + take * n) + frac
        seg = np.interp(grid, np.arange(x.size), np.real(x)).reshape(take, n)
    else:
        seg = np.real(x[start : start + take * n]).reshape(take, n)
    # sample k of the window is (k - n//2) samples from the decision instant;
    # linspace over the same range would put the step at spans/(n-1) and slide
    # the whole eye sideways by half a sample
    t = (np.arange(n) - n // 2) / float(sps)

    fig, ax = plt.subplots(figsize=(6.0, 3.4))
    ax.plot(t, seg.T, color="#1f77b4", alpha=0.06, linewidth=0.8)
    ax.axvline(0.0, color="#d62728", linewidth=0.9, linestyle="--")
    ax.set_xlabel("symbol periods from the sampling instant")
    ax.set_ylabel("in-phase amplitude")
    ax.set_title(title)
    ax.grid(alpha=0.25)
    return _save(fig, path)


def constellation_plot(symbols: np.ndarray, path: str | Path, *,
                       reference: np.ndarray | None = None,
                       title: str = "Constellation", tail: int = 3000) -> str:
    s = np.asarray(symbols)[-tail:]
    scale = np.sqrt(np.mean(np.abs(s) ** 2)) or 1.0
    s = s / scale

    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    ax.scatter(s.real, s.imag, s=3, alpha=0.25, color="#1f77b4", linewidths=0)
    if reference is not None:
        ax.scatter(np.real(reference), np.imag(reference), s=70,
                   facecolors="none", edgecolors="#d62728", linewidths=1.4)
    lim = max(1.6, float(np.percentile(np.abs(s), 99.5)) * 1.25)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.set_xlabel("I")
    ax.set_ylabel("Q")
    ax.set_title(title)
    ax.grid(alpha=0.25)
    return _save(fig, path)


def timing_trace(error: np.ndarray, path: str | Path, *,
                 converged_at: int | None = None, reference_error: np.ndarray | None = None,
                 title: str = "Timing loop") -> str:
    """TED output and, when the harness has it, the true timing error.

    The TED trace is what the plug-in can see. The reference trace is what the
    harness can measure. Plotting them together is how a claim that the loop
    converged stops being self-referential.
    """
    err = np.asarray(error)
    n_axes = 1 if reference_error is None else 2
    fig, axes = plt.subplots(n_axes, 1, figsize=(6.4, 2.4 * n_axes), sharex=True)
    axes = np.atleast_1d(axes)

    axes[0].plot(err, color="#c7c7c7", linewidth=0.5, label="raw TED")
    axes[0].plot(smoothed_error(err, 128), color="#1f77b4", linewidth=1.2,
                 label="smoothed (128)")
    axes[0].axhline(0.0, color="#444", linewidth=0.7)
    axes[0].set_ylabel("TED output")
    axes[0].legend(loc="upper right", fontsize=8)
    axes[0].grid(alpha=0.25)

    if reference_error is not None:
        axes[1].plot(np.asarray(reference_error), color="#2ca02c", linewidth=0.8)
        axes[1].axhline(0.0, color="#444", linewidth=0.7)
        axes[1].set_ylabel("timing error\n(symbol periods)")
        axes[1].set_ylim(-0.5, 0.5)
        axes[1].grid(alpha=0.25)

    if converged_at is not None:
        for ax in axes:
            ax.axvline(converged_at, color="#d62728", linewidth=1.0,
                       linestyle="--")
        axes[0].annotate(f"converged @ {converged_at}",
                         xy=(converged_at, axes[0].get_ylim()[1]),
                         xytext=(6, -12), textcoords="offset points",
                         fontsize=8, color="#d62728")

    axes[-1].set_xlabel("symbol index")
    axes[0].set_title(title)
    return _save(fig, path)


def cma_trace(error: np.ndarray, path: str | Path,
              title: str = "CMA convergence") -> str:
    e = np.asarray(error) ** 2
    win = max(1, e.size // 400)
    sm = np.convolve(e, np.ones(win) / win, mode="valid")
    fig, ax = plt.subplots(figsize=(6.0, 2.6))
    ax.semilogy(np.maximum(sm, 1e-12), color="#9467bd", linewidth=1.0)
    ax.set_xlabel("symbol index")
    ax.set_ylabel(r"mean $(|y|^2-R_2)^2$")
    ax.set_title(title)
    ax.grid(alpha=0.25, which="both")
    return _save(fig, path)


def chain_summary(rows: list[dict], path: str | Path,
                  title: str = "S3 across the corpus") -> str:
    """EVM and carrier lock against SNR, one marker per corpus file."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.0, 3.4))
    mods = sorted({r["modulation"] for r in rows})
    colours = plt.cm.tab10(np.linspace(0, 1, max(len(mods), 3)))

    for c, m in zip(colours, mods):
        sub = [r for r in rows if r["modulation"] == m]
        a1.scatter([r["snr_db"] for r in sub], [r["evm_percent"] for r in sub],
                   s=34, color=c, label=m)
        a2.scatter([r["snr_db"] for r in sub], [r["carrier_lock"] for r in sub],
                   s=34, color=c, label=m)

    a1.set_xlabel("SNR (dB)")
    a1.set_ylabel("EVM (%)")
    a1.set_title("EVM vs SNR")
    a1.grid(alpha=0.25)
    a1.legend(fontsize=8)

    a2.axhline(0.60, color="#d62728", linestyle="--", linewidth=0.9)
    a2.set_xlabel("SNR (dB)")
    a2.set_ylabel("carrier lock metric")
    a2.set_ylim(0, 1.05)
    a2.set_title("Carrier lock vs SNR")
    a2.grid(alpha=0.25)

    fig.suptitle(title)
    # suptitle sits on top of the axes titles without this; the charts end up
    # in a report, so the layout is part of the deliverable
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return _save(fig, path)
