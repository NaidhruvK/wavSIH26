import { scoresArePercent, scoreLabel } from './scoreFormat.js';

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
 *
 * Scores are scaled to percent ONLY when the stage's score is a fraction and
 * every value is in [0, 1] - see utils/scoreFormat.js for why S3 and S4 are
 * not. `isPercent` and `axisTitle` tell the chart how to label the axis.
 */
export function parseHypothesesData(hypotheses, stageName) {
  if (!Array.isArray(hypotheses) || hypotheses.length === 0) return null;

  const sorted = [...hypotheses]
    .map(h => ({
      value: String(h.value || h.label || 'unknown'),
      score: typeof h.score === 'number' ? h.score : 0.0,
      evidence: String(h.evidence || ''),
    }))
    .sort((a, b) => a.score - b.score); // Ascending for horizontal Plotly bars (top is highest)

  const isPercent = scoresArePercent(stageName, sorted.map(s => s.score));
  return {
    labels: sorted.map(s => s.value),
    scores: sorted.map(s => (isPercent ? s.score * 100 : s.score)),
    evidence: sorted.map(s => s.evidence),
    highestCandidate: sorted[sorted.length - 1]?.value || null,
    isPercent,
    axisTitle: isPercent ? `${scoreLabel(stageName)} (%)` : scoreLabel(stageName),
  };
}

/**
 * S3 operating-envelope measurements, transcribed from reports/s3_envelope.csv
 * (columns: modulation, snr_db, evm_percent, carrier_lock). Every value below
 * appears verbatim in that CSV -- do not add a point that is not in it.
 *
 * `evm` is null for 2FSK and 4FSK BECAUSE IT WAS NEVER MEASURED: EVM is a
 * distance to a fixed constellation point, and the FSK receiver is a
 * non-coherent frequency discriminator with no constellation to measure
 * against. `evm_percent` is empty in all four FSK rows of the CSV.
 *
 * Until 10 Sep this block carried invented EVM curves for both FSK schemes
 * (2FSK 18.50/14.20/10.10/6.80 at SNR 10/12/15/20; 4FSK 19.20/15.00/11.20/7.50)
 * under this same "measured" comment. Neither the EVM values nor the SNR points
 * existed in the CSV, and the EVM-vs-SNR chart plotted them as measurements.
 * Carrier-lock is the FSK figure that WAS measured, and it is what is kept.
 */
export const EMPIRICAL_ENVELOPE_DATA = {
  bpsk: [
    { snr: 8, evm: 23.479, lock: 0.9294 },
    { snr: 10, evm: 19.603, lock: 0.9488 },
    { snr: 13, evm: 15.419, lock: 0.9658 },
    { snr: 16, evm: 12.717, lock: 0.9747 },
    { snr: 20, evm: 10.547, lock: 0.9809 },
  ],
  qpsk: [
    { snr: 8, evm: 20.189, lock: 0.8401 },
    { snr: 10, evm: 16.120, lock: 0.8964 },
    { snr: 13, evm: 11.467, lock: 0.9468 },
    { snr: 16, evm: 8.143, lock: 0.9730 },
    { snr: 20, evm: 5.158, lock: 0.9891 },
  ],
  '8psk': [
    { snr: 8, evm: 20.041, lock: 0.4894 },
    { snr: 10, evm: 16.059, lock: 0.6415 },
    { snr: 13, evm: 11.431, lock: 0.8016 },
    { snr: 16, evm: 8.115, lock: 0.8953 },
    { snr: 20, evm: 5.138, lock: 0.9568 },
  ],
  '16qam': [
    { snr: 13, evm: 12.543, lock: 0.8649 },
    { snr: 15, evm: 10.389, lock: 0.9074 },
    { snr: 18, evm: 8.093, lock: 0.9170 },
    { snr: 22, evm: 6.280, lock: 0.9222 },
  ],
  '2fsk': [
    { snr: 5, evm: null, lock: 0.8258 },
    { snr: 8, evm: null, lock: 0.8761 },
    { snr: 12, evm: null, lock: 0.9216 },
    { snr: 16, evm: null, lock: 0.9504 },
  ],
  '4fsk': [
    { snr: 7, evm: null, lock: 0.7975 },
    { snr: 10, evm: null, lock: 0.8561 },
    { snr: 14, evm: null, lock: 0.9090 },
    { snr: 18, evm: null, lock: 0.9425 },
  ],
};

/**
 * Lowest SNR (dB) at which reports/s3_envelope.csv records measured_ber == 0
 * for that scheme, straight off the `measured_ber` column.
 *
 * READ THIS WITH `ZERO_ERROR_THRESHOLD_IS_EXACT` BELOW. For four of the six
 * schemes the lowest SNR that was TESTED already decoded with zero errors, so
 * the number is an UPPER BOUND on the threshold -- the real one is somewhere
 * at or below it, and the sweep never went low enough to find it. Only 8PSK
 * has a measured crossing inside the swept range (4.8e-2 at 8 dB, 2.5e-4 at
 * 10 dB, 0 at 13 dB).
 *
 * "ZERO" IS A DETECTION LIMIT, NOT A ZERO. The study compares at most 40,000
 * demodulated bits per file, so measured_ber == 0 means "no bit errors in
 * 40,000" -- a true BER below roughly 2.5e-05, not the absence of errors. Say
 * it that way to anyone who asks; the sweep cannot resolve finer.
 *
 * 16QAM is the least settled of the six: 4.75e-04 at 13 dB, 2.5e-04 at 15 dB,
 * 2.75e-04 at 18 dB, and only 0 at 22 dB. Note this does NOT contradict
 * demo/README.md's whole-chain envelope of >= 15 dB for 16QAM. These are S3
 * output errors, and the rate-1/2 K=7 convolutional code downstream corrects
 * them: the 16QAM capture at 15 dB decodes to the exact transmitted bits
 * (tests/e2e/test_decoded_bits_match_transmitter.py). A raw demodulator error
 * rate is not a chain failure.
 *
 * Corrected 10 Sep. This map previously read 2fsk 10.0, 4fsk 10.0 and
 * 16qam 20.0, none of which appeared in the CSV it claims to come from, and
 * the CSV itself was stale -- regenerated from current code the same day,
 * which moved 8PSK and 16QAM's measured_ber column.
 */
export const ZERO_ERROR_SNR_THRESHOLDS = {
  bpsk: 8.0,
  qpsk: 8.0,
  '2fsk': 5.0,
  '4fsk': 7.0,
  '8psk': 13.0,
  '16qam': 22.0,
};

/**
 * true  -> a crossing was actually observed inside the swept SNR range.
 * false -> the lowest SNR tested was already error-free, so the paired value in
 *          ZERO_ERROR_SNR_THRESHOLDS is an upper bound and should be rendered
 *          and spoken about as "<= x dB", never as "the threshold is x dB".
 */
export const ZERO_ERROR_THRESHOLD_IS_EXACT = {
  bpsk: false,
  qpsk: false,
  '2fsk': false,
  '4fsk': false,
  '8psk': true,
  '16qam': true,
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
    if (s === normMod) return '#3ecf8e';
    if (s === '16qam') return '#b083e8';
    if (s === '8psk') return '#e0a83e';
    if (s.includes('fsk')) return '#6fd0ec';
    return '#4db8d8';
  });

  const trace = {
    x: xLabels,
    y: yValues,
    type: 'bar',
    name: 'Required Min SNR',
    marker: {
      color: colors,
      line: { color: 'rgba(232, 237, 244, 0.4)', width: 1 },
    },
    // A scheme whose lowest TESTED SNR was already error-free has an upper
    // bound, not a threshold, and must not be drawn as though the crossing was
    // observed. ZERO_ERROR_THRESHOLD_IS_EXACT says which is which.
    text: schemes.map((sch, i) =>
      ZERO_ERROR_THRESHOLD_IS_EXACT[sch] === false ? `≤ ${yValues[i]} dB` : `${yValues[i]} dB`),
    textposition: 'outside',
    textfont: { color: '#97a3b6', size: 11, family: "'IBM Plex Mono', ui-monospace, monospace" },
    customdata: schemes.map(sch =>
      ZERO_ERROR_THRESHOLD_IS_EXACT[sch] === false
        ? 'upper bound - lowest SNR tested was already error-free'
        : 'measured crossing inside the swept range'),
    hovertemplate:
      '<b>%{x}</b><br>Zero-error SNR: %{y} dB<br>%{customdata}<extra></extra>',
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
        color: '#e0564d',
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
      font: { color: '#e0564d', size: 10, weight: 700 },
      bgcolor: 'rgba(9, 12, 18, 0.85)',
    });
  }

  const maxY = Math.max(25, (Number(currentSnr) || 0) + 4);

  const layout = {
    title: {
      text: 'S3 Zero-Error SNR Gates by Modulation Scheme',
      font: { color: '#e8edf4', size: 12, weight: 600 },
      x: 0.02,
    },
    xaxis: {
      title: { text: 'Modulation Scheme', font: { color: '#97a3b6', size: 11 } },
      tickfont: { color: '#97a3b6' },
    },
    yaxis: {
      title: { text: 'Required Channel SNR (dB)', font: { color: '#97a3b6', size: 11 } },
      range: [0, maxY],
      dtick: 5,
    },
    shapes,
    annotations,
  };

  return { traces, layout };
}
