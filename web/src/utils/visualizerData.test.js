import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  downsampleUniform,
  parsePsdData,
  parseConstellationData,
  parseRankProfileData,
  parseHypothesesData,
  EMPIRICAL_ENVELOPE_DATA,
} from './visualizerData.js';

test('downsampleUniform preserves length if <= target', () => {
  const arr = [1, 2, 3, 4, 5];
  const out = downsampleUniform(arr, 10);
  assert.equal(out.length, 5);
  assert.deepEqual(out, [1, 2, 3, 4, 5]);
});

test('downsampleUniform decimates evenly and preserves endpoints', () => {
  const arr = Array.from({ length: 100 }, (_, i) => i);
  const out = downsampleUniform(arr, 10);
  assert.equal(out.length, 10);
  assert.equal(out[0], 0);
  assert.equal(out[out.length - 1], 99);
});

test('parsePsdData extracts spectrum and detects peak frequency', () => {
  const raw = {
    freqs: [-1000, 0, 1000],
    psd_db: [-60.5, -12.3, -58.2],
    noise_floor_db: -65.0,
  };
  const parsed = parsePsdData(raw);
  assert.ok(parsed);
  assert.equal(parsed.freqs.length, 3);
  assert.equal(parsed.peakFreq, 0);
  assert.equal(parsed.peakPsd, -12.3);
  assert.equal(parsed.noiseFloorDb, -65.0);
});

test('parsePsdData downsamples when freqs exceed maxPoints', () => {
  const freqs = Array.from({ length: 2000 }, (_, i) => i - 1000);
  const psd = Array.from({ length: 2000 }, () => -50.0);
  const parsed = parsePsdData({ freqs, psd_db: psd }, 256);
  assert.ok(parsed);
  assert.equal(parsed.renderedPoints, 256);
  assert.equal(parsed.totalPoints, 2000);
});

test('parsePsdData returns null on invalid or mismatched arrays', () => {
  assert.equal(parsePsdData(null), null);
  assert.equal(parsePsdData({ freqs: [1, 2], psd_db: [1] }), null);
  assert.equal(parsePsdData({ freqs: [] }), null);
});

test('parseConstellationData extracts I/Q coordinates and scales bounds', () => {
  const raw = [
    { i: 1.0, q: 1.0 },
    { i: -1.0, q: 1.0 },
    { i: -1.0, q: -1.0 },
    { i: 1.0, q: -1.0 },
  ];
  const parsed = parseConstellationData(raw, 500);
  assert.ok(parsed);
  assert.equal(parsed.renderedCount, 4);
  assert.deepEqual(parsed.iPoints, [1, -1, -1, 1]);
  assert.deepEqual(parsed.qPoints, [1, 1, -1, -1]);
  assert.ok(parsed.bound >= 1.2);
});

test('parseConstellationData downsamples arrays larger than maxPoints', () => {
  const raw = Array.from({ length: 1500 }, (_, i) => ({ i: Math.cos(i), q: Math.sin(i) }));
  const parsed = parseConstellationData(raw, 200);
  assert.ok(parsed);
  assert.equal(parsed.originalCount, 1500);
  assert.equal(parsed.renderedCount, 200);
});

test('parseRankProfileData sorts periods and identifies collapse peak', () => {
  const raw = {
    "96": 36,
    "8": 0,
    "48": 12,
    "12": 0,
  };
  const parsed = parseRankProfileData(raw);
  assert.ok(parsed);
  assert.deepEqual(parsed.periods, [8, 12, 48, 96]);
  assert.deepEqual(parsed.deficiencies, [0, 0, 12, 36]);
  assert.equal(parsed.peakPeriod, 96);
  assert.equal(parsed.peakDeficiency, 36);
});

test('parseHypothesesData sorts ascending by score for horizontal Plotly chart', () => {
  const hyps = [
    { value: 'bpsk', score: 0.05, evidence: 'Weak residual' },
    { value: 'qpsk', score: 0.92, evidence: '4-quadrant cluster' },
    { value: '8psk', score: 0.03, evidence: 'Low 8th power' },
  ];
  const parsed = parseHypothesesData(hyps);
  assert.ok(parsed);
  assert.deepEqual(parsed.labels, ['8psk', 'bpsk', 'qpsk']);
  assert.equal(parsed.highestCandidate, 'qpsk');
  assert.equal(parsed.scores[2], 92);
});

test('EMPIRICAL_ENVELOPE_DATA contains standard modulation schemes', () => {
  assert.ok(EMPIRICAL_ENVELOPE_DATA.qpsk);
  assert.ok(EMPIRICAL_ENVELOPE_DATA.bpsk);
  assert.ok(EMPIRICAL_ENVELOPE_DATA['16qam']);
  // Monotonic check: higher SNR has lower or equal EVM
  const qpsk = EMPIRICAL_ENVELOPE_DATA.qpsk;
  assert.ok(qpsk[qpsk.length - 1].evm < qpsk[0].evm);
});

test('ZERO_ERROR_SNR_THRESHOLDS defines exact gate values for all 6 schemes', async () => {
  const { ZERO_ERROR_SNR_THRESHOLDS } = await import('./visualizerData.js');
  assert.equal(ZERO_ERROR_SNR_THRESHOLDS.bpsk, 8.0);
  assert.equal(ZERO_ERROR_SNR_THRESHOLDS.qpsk, 8.0);
  assert.equal(ZERO_ERROR_SNR_THRESHOLDS['2fsk'], 10.0);
  assert.equal(ZERO_ERROR_SNR_THRESHOLDS['4fsk'], 10.0);
  assert.equal(ZERO_ERROR_SNR_THRESHOLDS['8psk'], 13.0);
  assert.equal(ZERO_ERROR_SNR_THRESHOLDS['16qam'], 20.0);
});

test('formatFrequency correctly formats Hz, kHz, MHz and invalid values', async () => {
  const { formatFrequency } = await import('./visualizerData.js');
  assert.equal(formatFrequency(null), '—');
  assert.equal(formatFrequency(undefined), '—');
  assert.equal(formatFrequency('abc'), '—');
  assert.equal(formatFrequency(500), '500 Hz');
  assert.equal(formatFrequency(12500), '12.5 kHz');
  assert.equal(formatFrequency(-45000), '-45.0 kHz');
  assert.equal(formatFrequency(20000000), '20.00 MHz');
});

test('evaluateRunEnvelope accurately verifies in-spec signal', async () => {
  const { evaluateRunEnvelope } = await import('./visualizerData.js');
  const mockReport = {
    envelope_verdict: 'in_envelope',
    stages: [
      { stage: 's0_ingest', status: 'completed', values: { fs: 2000000 } },
      { stage: 's1_detect', status: 'completed', values: { snr_db: 14.5, occupied_bw_hz: 50000 } },
      { stage: 's2_estimate', status: 'completed', values: { sps: 4.0, cfo_hz: 1200 } },
      { stage: 's3_receive', status: 'completed', values: { modulation: 'qpsk', evm_percent: 6.2 } },
    ],
  };

  const evalResult = evaluateRunEnvelope(null, mockReport);
  assert.equal(evalResult.verdict, 'in_envelope');
  assert.equal(evalResult.checks.s0InBounds, true);
  assert.equal(evalResult.checks.s1InBounds, true);
  assert.equal(evalResult.checks.s2InBounds, true);
  assert.equal(evalResult.checks.s3InBounds, true);
  assert.equal(evalResult.refusal, null);
  assert.equal(evalResult.run.snr, 14.5);
  assert.equal(evalResult.run.modulation, 'qpsk');
  assert.equal(evalResult.run.modThreshold, 8.0);
});

test('evaluateRunEnvelope detects out_of_envelope refusal and stage violations', async () => {
  const { evaluateRunEnvelope } = await import('./visualizerData.js');
  const mockReport = {
    envelope_verdict: 'out_of_envelope',
    stages: [
      { stage: 's0_ingest', status: 'completed', values: { fs: 2000000 } },
      {
        stage: 's1_detect',
        status: 'out_of_envelope',
        reason: 'SNR -8.0 dB is below minimum envelope (-5.0 dB)',
        values: { snr_db: -8.0, occupied_bw_hz: 500 },
      },
    ],
  };

  const evalResult = evaluateRunEnvelope(null, mockReport);
  assert.equal(evalResult.verdict, 'out_of_envelope');
  assert.equal(evalResult.checks.s1InBounds, false);
  assert.ok(evalResult.refusal);
  assert.equal(evalResult.refusal.stage, 's1_detect');
  assert.equal(evalResult.refusal.reason, 'SNR -8.0 dB is below minimum envelope (-5.0 dB)');
});

test('buildThresholdBarChartData constructs Plotly traces with reference line', async () => {
  const { buildThresholdBarChartData } = await import('./visualizerData.js');
  const chart = buildThresholdBarChartData(undefined, 12.0, 'qpsk');
  assert.ok(chart.traces && chart.traces.length === 1);
  const trace = chart.traces[0];
  assert.deepEqual(trace.x, ['BPSK', 'QPSK', '2FSK', '4FSK', '8PSK', '16QAM']);
  assert.deepEqual(trace.y, [8, 8, 10, 10, 13, 20]);
  assert.equal(trace.type, 'bar');

  // Verify reference line shape and annotation for current SNR
  assert.equal(chart.layout.shapes.length, 1);
  assert.equal(chart.layout.shapes[0].y0, 12.0);
  assert.equal(chart.layout.annotations.length, 1);
  assert.ok(chart.layout.annotations[0].text.includes('12.0 dB'));
});
