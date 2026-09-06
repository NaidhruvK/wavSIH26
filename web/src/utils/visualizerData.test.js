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
