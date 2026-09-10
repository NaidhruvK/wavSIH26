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
  '2fsk': [
    { snr: 10, evm: 18.50, lock: 0.88 },
    { snr: 12, evm: 14.20, lock: 0.94 },
    { snr: 15, evm: 10.10, lock: 0.97 },
    { snr: 20, evm: 6.80, lock: 0.99 },
  ],
  '4fsk': [
    { snr: 10, evm: 19.20, lock: 0.85 },
    { snr: 12, evm: 15.00, lock: 0.92 },
    { snr: 15, evm: 11.20, lock: 0.96 },
    { snr: 20, evm: 7.50, lock: 0.98 },
  ],
};

/**
 * Declared S3 Zero-Error SNR Gate thresholds (dB) per modulation.
 */
export const ZERO_ERROR_SNR_THRESHOLDS = {
  bpsk: 8.0,
  qpsk: 8.0,
  '2fsk': 10.0,
  '4fsk': 10.0,
  '8psk': 13.0,
  '16qam': 20.0,
};

/**
 * Declared pipeline operating envelope boundaries.
 */
export const DEFAULT_ENVELOPE_BOUNDS = {
  s0: {
    minFs: 8000.0,
    maxFs: 20000000.0,
    label: '8 kHz – 20 MHz',
  },
  s1: {
    minSnr: -5.0,
    minObw: 1000.0,
    snrLabel: '≥ -5.0 dB',
    obwLabel: '≥ 1.0 kHz',
  },
  s2: {
    minSps: 2.5,
    maxSps: 40.0,
    minCfo: -50000.0,
    maxCfo: 50000.0,
    spsLabel: '2.5 – 40.0',
    cfoLabel: '±50.0 kHz',
  },
  s3: {
    thresholds: ZERO_ERROR_SNR_THRESHOLDS,
  },
};

/**
 * Helper to format frequencies into Hz, kHz, or MHz string.
 */
export function formatFrequency(hz) {
  if (hz === null || hz === undefined || Number.isNaN(Number(hz))) return '—';
  const num = Number(hz);
  const abs = Math.abs(num);
  if (abs >= 1000000) return `${(num / 1000000).toFixed(2)} MHz`;
  if (abs >= 1000) return `${(num / 1000).toFixed(1)} kHz`;
  return `${num.toFixed(0)} Hz`;
}

/**
 * Evaluates run metrics against declared operating envelope bounds.
 */
export function evaluateRunEnvelope(envelope, runReport) {
  const s0Spec = envelope?.stages?.s0_ingest;
  const s1Spec = envelope?.stages?.s1_detect;
  const s2Spec = envelope?.stages?.s2_estimate;
  const s3Spec = envelope?.stages?.s3_receive;

  const minFs = Array.isArray(s0Spec?.sample_rate_range_hz)
    ? Number(s0Spec.sample_rate_range_hz[0])
    : DEFAULT_ENVELOPE_BOUNDS.s0.minFs;
  const maxFs = Array.isArray(s0Spec?.sample_rate_range_hz)
    ? Number(s0Spec.sample_rate_range_hz[1])
    : DEFAULT_ENVELOPE_BOUNDS.s0.maxFs;

  const minSnr = typeof s1Spec?.min_snr_db === 'number'
    ? s1Spec.min_snr_db
    : DEFAULT_ENVELOPE_BOUNDS.s1.minSnr;
  const minObw = typeof s1Spec?.occupied_bandwidth_min_hz === 'number'
    ? s1Spec.occupied_bandwidth_min_hz
    : DEFAULT_ENVELOPE_BOUNDS.s1.minObw;

  const minSps = Array.isArray(s2Spec?.sps_range)
    ? Number(s2Spec.sps_range[0])
    : DEFAULT_ENVELOPE_BOUNDS.s2.minSps;
  const maxSps = Array.isArray(s2Spec?.sps_range)
    ? Number(s2Spec.sps_range[1])
    : DEFAULT_ENVELOPE_BOUNDS.s2.maxSps;

  const minCfo = Array.isArray(s2Spec?.cfo_range_hz)
    ? Number(s2Spec.cfo_range_hz[0])
    : DEFAULT_ENVELOPE_BOUNDS.s2.minCfo;
  const maxCfo = Array.isArray(s2Spec?.cfo_range_hz)
    ? Number(s2Spec.cfo_range_hz[1])
    : DEFAULT_ENVELOPE_BOUNDS.s2.maxCfo;

  const thresholds = {
    ...ZERO_ERROR_SNR_THRESHOLDS,
    ...(s3Spec?.zero_error_snr_thresholds || {}),
  };

  const stages = runReport?.stages || [];
  const s0 = stages.find(s => s.stage === 's0_ingest');
  const s1 = stages.find(s => s.stage === 's1_detect');
  const s2 = stages.find(s => s.stage === 's2_estimate');
  const s3 = stages.find(s => s.stage === 's3_receive');

  const runFs = s0?.values?.fs !== undefined && s0?.values?.fs !== null
    ? Number(s0.values.fs)
    : (runReport?.file_meta?.sample_rate ? Number(runReport.file_meta.sample_rate) : null);
  const runSnr = s1?.values?.snr_db !== undefined && s1?.values?.snr_db !== null ? Number(s1.values.snr_db) : null;
  const runObw = s1?.values?.occupied_bw_hz !== undefined && s1?.values?.occupied_bw_hz !== null ? Number(s1.values.occupied_bw_hz) : null;
  const runSps = s2?.values?.sps !== undefined && s2?.values?.sps !== null ? Number(s2.values.sps) : null;
  const runCfo = s2?.values?.cfo_hz !== undefined && s2?.values?.cfo_hz !== null ? Number(s2.values.cfo_hz) : null;
  const runMod = s3?.values?.modulation ? String(s3.values.modulation).toLowerCase() : null;
  const runEvm = s3?.values?.evm_percent !== undefined && s3?.values?.evm_percent !== null ? Number(s3.values.evm_percent) : null;

  const s0InBounds = runFs !== null ? (runFs >= minFs && runFs <= maxFs) : null;
  const s1InBounds = (runSnr !== null || runObw !== null)
    ? ((runSnr === null || runSnr >= minSnr) && (runObw === null || runObw >= minObw))
    : null;
  const s2InBounds = (runSps !== null || runCfo !== null)
    ? ((runSps === null || (runSps >= minSps && runSps <= maxSps)) && (runCfo === null || (runCfo >= minCfo && runCfo <= maxCfo)))
    : null;

  const modThreshold = runMod && thresholds[runMod] !== undefined ? thresholds[runMod] : null;
  const s3InBounds = (runSnr !== null && modThreshold !== null) ? (runSnr >= modThreshold) : null;

  const verdict = runReport?.envelope_verdict || 'pending';
  const outOfEnvelopeStage = stages.find(s => s.status === 'out_of_envelope');

  return {
    bounds: {
      minFs,
      maxFs,
      minSnr,
      minObw,
      minSps,
      maxSps,
      minCfo,
      maxCfo,
      thresholds,
    },
    run: {
      fs: runFs,
      snr: runSnr,
      obw: runObw,
      sps: runSps,
      cfo: runCfo,
      modulation: runMod,
      evm: runEvm,
      modThreshold,
    },
    checks: {
      s0InBounds,
      s1InBounds,
      s2InBounds,
      s3InBounds,
    },
    verdict,
    refusal: outOfEnvelopeStage ? {
      stage: outOfEnvelopeStage.stage,
      reason: outOfEnvelopeStage.reason || 'Outside declared operating envelope',
    } : null,
  };
}

/**
 * Builds Plotly bar chart data for S3 Zero-Error SNR Thresholds.
 */
export function buildThresholdBarChartData(thresholds = ZERO_ERROR_SNR_THRESHOLDS, currentSnr = null, currentMod = null) {
  const schemes = ['bpsk', 'qpsk', '2fsk', '4fsk', '8psk', '16qam'];
  const xLabels = schemes.map(s => s.toUpperCase());
  const yValues = schemes.map(s => (thresholds[s] !== undefined ? thresholds[s] : ZERO_ERROR_SNR_THRESHOLDS[s]));

  const normMod = currentMod ? String(currentMod).toLowerCase() : null;

  const colors = schemes.map(s => {
    if (s === normMod) return '#10b981';
    if (s === '16qam') return '#a855f7';
    if (s === '8psk') return '#f59e0b';
    if (s.includes('fsk')) return '#38bdf8';
    return '#06b6d4';
  });

  const trace = {
    x: xLabels,
    y: yValues,
    type: 'bar',
    name: 'Required Min SNR',
    marker: {
      color: colors,
      line: { color: '#ffffff', width: 1 },
    },
    text: yValues.map(v => `${v} dB`),
    textposition: 'outside',
    textfont: { color: '#cbd5e1', size: 11, family: 'ui-monospace, monospace' },
    hovertemplate: '<b>%{x}</b><br>Zero-Error SNR Threshold: %{y} dB<extra></extra>',
  };

  const traces = [trace];
  const shapes = [];
  const annotations = [];

  if (currentSnr !== null && !Number.isNaN(Number(currentSnr))) {
    const numSnr = Number(currentSnr);
    shapes.push({
      type: 'line',
      xref: 'paper',
      x0: 0,
      x1: 1,
      yref: 'y',
      y0: numSnr,
      y1: numSnr,
      line: {
        color: '#f43f5e',
        width: 2,
        dash: 'dash',
      },
    });

    annotations.push({
      xref: 'paper',
      x: 0.98,
      yref: 'y',
      y: numSnr,
      text: `Measured Run SNR: ${numSnr.toFixed(1)} dB`,
      showarrow: false,
      xanchor: 'right',
      yanchor: 'bottom',
      font: { color: '#f43f5e', size: 10, weight: 700 },
      bgcolor: 'rgba(15, 23, 42, 0.85)',
    });
  }

  const maxY = Math.max(25, (Number(currentSnr) || 0) + 4);

  const layout = {
    title: {
      text: 'S3 Zero-Error SNR Gates by Modulation Scheme',
      font: { color: '#fff', size: 13, weight: 700 },
      x: 0.02,
    },
    xaxis: {
      title: { text: 'Modulation Scheme', font: { color: '#94a3b8', size: 11 } },
      tickfont: { color: '#cbd5e1' },
    },
    yaxis: {
      title: { text: 'Required Channel SNR (dB)', font: { color: '#94a3b8', size: 11 } },
      range: [0, maxY],
      dtick: 5,
    },
    shapes,
    annotations,
  };

  return { traces, layout };
}
