/**
 * Data transformation and downsampling utilities for RF Signal Visualizations.
 * Pure functions with zero DOM / window dependencies for reliable testing.
 */

/**
 * Uniformly downsamples an array to targetLength while preserving endpoints.
 */
export function downsampleUniform(array, targetLength = 1000) {
  if (!Array.isArray(array) || array.length <= targetLength || targetLength <= 0) {
    return array || [];
  }
  const len = array.length;
  const result = new Array(targetLength);
  const step = (len - 1) / (targetLength - 1);
  for (let i = 0; i < targetLength; i++) {
    const idx = Math.min(Math.round(i * step), len - 1);
    result[i] = array[idx];
  }
  return result;
}

/**
 * Parses raw PSD artifact JSON: { freqs, psd_db, noise_floor_db }.
 */
export function parsePsdData(raw, maxPoints = 1024) {
  if (!raw || typeof raw !== 'object') return null;

  const freqs = raw.freqs || raw.frequencies;
  const psd = raw.psd_db || raw.psd || raw.power;

  if (!Array.isArray(freqs) || !Array.isArray(psd) || freqs.length === 0 || freqs.length !== psd.length) {
    return null;
  }

  const noiseFloorDb = typeof raw.noise_floor_db === 'number' ? raw.noise_floor_db : null;

  // Downsample if dataset exceeds maxPoints
  let finalFreqs = freqs;
  let finalPsd = psd;

  if (freqs.length > maxPoints) {
    const step = (freqs.length - 1) / (maxPoints - 1);
    finalFreqs = [];
    finalPsd = [];
    for (let i = 0; i < maxPoints; i++) {
      const idx = Math.min(Math.round(i * step), freqs.length - 1);
      finalFreqs.push(Number(freqs[idx]));
      finalPsd.push(Number(psd[idx]));
    }
  } else {
    finalFreqs = freqs.map(Number);
    finalPsd = psd.map(Number);
  }

  // Find peak
  let peakPsd = -Infinity;
  let peakFreq = 0;
  for (let i = 0; i < finalPsd.length; i++) {
    if (finalPsd[i] > peakPsd) {
      peakPsd = finalPsd[i];
      peakFreq = finalFreqs[i];
    }
  }

  return {
    freqs: finalFreqs,
    psdDb: finalPsd,
    noiseFloorDb,
    peakFreq,
    peakPsd: peakPsd !== -Infinity ? peakPsd : null,
    totalPoints: freqs.length,
    renderedPoints: finalFreqs.length,
  };
}

/**
 * Parses raw Constellation IQ artifact: array of { i, q } or [i, q].
 * Downsamples to maxPoints to preserve browser responsiveness at 60 FPS.
 */
export function parseConstellationData(raw, maxPoints = 1000) {
  if (!raw) return null;

  let points = [];
  if (Array.isArray(raw)) {
    points = raw;
  } else if (raw.symbols && Array.isArray(raw.symbols)) {
    points = raw.symbols;
  } else if (raw.points && Array.isArray(raw.points)) {
    points = raw.points;
  } else {
    return null;
  }

  if (points.length === 0) return null;

  // Extract I and Q
  const parsed = [];
  for (let idx = 0; idx < points.length; idx++) {
    const pt = points[idx];
    let iVal = NaN;
    let qVal = NaN;

    if (pt && typeof pt === 'object') {
      if ('i' in pt && 'q' in pt) {
        iVal = Number(pt.i);
        qVal = Number(pt.q);
      } else if (Array.isArray(pt) && pt.length >= 2) {
        iVal = Number(pt[0]);
        qVal = Number(pt[1]);
      } else if ('real' in pt && 'imag' in pt) {
        iVal = Number(pt.real);
        qVal = Number(pt.imag);
      }
    }

    if (!Number.isNaN(iVal) && !Number.isNaN(qVal)) {
      parsed.push({ i: iVal, q: qVal });
    }
  }

  if (parsed.length === 0) return null;

  const originalCount = parsed.length;
  const sampled = downsampleUniform(parsed, maxPoints);

  const iPoints = sampled.map(p => p.i);
  const qPoints = sampled.map(p => p.q);

  // Compute bounding box
  let maxAbs = 1.0;
  for (let k = 0; k < sampled.length; k++) {
    const r = Math.abs(sampled[k].i);
    const im = Math.abs(sampled[k].q);
    if (r > maxAbs) maxAbs = r;
    if (im > maxAbs) maxAbs = im;
  }

  const bound = Math.ceil(maxAbs * 1.2 * 10) / 10;

  return {
    iPoints,
    qPoints,
    originalCount,
    renderedCount: sampled.length,
    bound: Math.max(bound, 1.5),
  };
}

/**
 * Parses raw GF(2) Rank Deficiency Profile artifact:
 * { "8": 0, "9": 0, ..., "96": 36, ... } or Array<{ period, deficiency }>.
 */
export function parseRankProfileData(raw) {
  if (!raw || typeof raw !== 'object') return null;

  const entries = [];

  if (Array.isArray(raw)) {
    for (const item of raw) {
      if (item && typeof item === 'object') {
        const p = Number(item.period ?? item.L ?? item.l);
        const d = Number(item.deficiency ?? item.rank_deficiency ?? item.d);
        if (!Number.isNaN(p) && !Number.isNaN(d)) {
          entries.push({ period: p, deficiency: d });
        }
      }
    }
  } else {
    for (const [key, val] of Object.entries(raw)) {
      const p = Number(key);
      const d = Number(val);
      if (!Number.isNaN(p) && !Number.isNaN(d)) {
        entries.push({ period: p, deficiency: d });
      }
    }
  }

  if (entries.length === 0) return null;

  // Sort ascending by period L
  entries.sort((a, b) => a.period - b.period);

  const periods = entries.map(e => e.period);
  const deficiencies = entries.map(e => e.deficiency);

  // Locate peaks
  let peakPeriod = null;
  let peakDeficiency = 0;

  for (let i = 0; i < entries.length; i++) {
    if (entries[i].deficiency > peakDeficiency) {
      peakDeficiency = entries[i].deficiency;
      peakPeriod = entries[i].period;
    }
  }

  return {
    periods,
    deficiencies,
    peakPeriod: peakDeficiency > 0 ? peakPeriod : null,
    peakDeficiency,
    totalEvaluated: entries.length,
  };
}

/**
 * Parses ranked hypotheses into bar chart series with evidence.
 */
export function parseHypothesesData(hypotheses) {
  if (!Array.isArray(hypotheses) || hypotheses.length === 0) return null;

  const sorted = [...hypotheses]
    .map(h => ({
      value: String(h.value || h.label || 'unknown'),
      score: typeof h.score === 'number' ? h.score : 0.0,
      evidence: String(h.evidence || ''),
    }))
    .sort((a, b) => a.score - b.score); // Ascending for horizontal Plotly bars (top is highest)

  return {
    labels: sorted.map(s => s.value),
    scores: sorted.map(s => s.score * 100),
    evidence: sorted.map(s => s.evidence),
    highestCandidate: sorted[sorted.length - 1]?.value || null,
  };
}

/**
 * Standard empirical S3 operating envelope data (measured across test zoo in reports/s3_envelope.csv).
 * Provides benchmark performance curves for BPSK, QPSK, 8PSK, 16QAM, 2FSK, 4FSK.
 */
export const EMPIRICAL_ENVELOPE_DATA = {
  bpsk: [
    { snr: 8, evm: 23.48, lock: 0.93 },
    { snr: 10, evm: 19.60, lock: 0.95 },
    { snr: 13, evm: 15.42, lock: 0.97 },
    { snr: 16, evm: 12.72, lock: 0.97 },
    { snr: 20, evm: 10.55, lock: 0.98 },
  ],
  qpsk: [
    { snr: 8, evm: 20.19, lock: 0.84 },
    { snr: 10, evm: 16.12, lock: 0.90 },
    { snr: 13, evm: 11.47, lock: 0.95 },
    { snr: 16, evm: 8.14, lock: 0.97 },
    { snr: 20, evm: 5.16, lock: 0.99 },
  ],
  '8psk': [
    { snr: 8, evm: 20.04, lock: 0.49 },
    { snr: 10, evm: 16.06, lock: 0.64 },
    { snr: 13, evm: 11.43, lock: 0.80 },
    { snr: 16, evm: 8.12, lock: 0.90 },
    { snr: 20, evm: 5.14, lock: 0.96 },
  ],
  '16qam': [
    { snr: 13, evm: 12.54, lock: 0.86 },
    { snr: 15, evm: 10.39, lock: 0.91 },
    { snr: 18, evm: 8.09, lock: 0.92 },
    { snr: 22, evm: 6.28, lock: 0.92 },
  ],
};
