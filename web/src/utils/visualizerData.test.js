import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
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

// ---------------------------------------------------------------------------
// The two blocks below used to assert that the constants equalled themselves,
// which is why fabricated 2FSK/4FSK EVM curves sat in EMPIRICAL_ENVELOPE_DATA
// under a "measured" comment for days with a green test beside them. These
// read reports/s3_envelope.csv instead: the constants are now checked against
// the file they claim to come from, so inventing a point fails the suite.
// ---------------------------------------------------------------------------

const CSV_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), '../../../reports/s3_envelope.csv');

function readEnvelopeCsv() {
  // split on newlines without regex escapes, so the line survives any
  // future mechanical edit of this file
  const lines = readFileSync(CSV_PATH, 'utf8').trim()
    .split(String.fromCharCode(10)).map(l => l.trim()).filter(Boolean);
  const header = lines[0].split(',');
  return lines.slice(1).map(line => {
    const cells = line.split(',');
    return Object.fromEntries(header.map((h, i) => [h, cells[i]]));
  });
}

test('EMPIRICAL_ENVELOPE_DATA matches reports/s3_envelope.csv point for point', () => {
  const rows = readEnvelopeCsv();
  assert.ok(rows.length > 0, 'envelope CSV is empty');

  for (const [scheme, points] of Object.entries(EMPIRICAL_ENVELOPE_DATA)) {
    for (const point of points) {
      const match = rows.find(
        r => r.modulation === scheme && Number(r.snr_db) === point.snr);
      assert.ok(match,
        `${scheme} @ ${point.snr} dB is plotted but is not a row in s3_envelope.csv`);

      const csvEvm = match.evm_percent === '' ? null : Number(match.evm_percent);
      if (csvEvm === null) {
        assert.equal(point.evm, null,
          `${scheme} @ ${point.snr} dB carries an EVM value but the CSV measured none`);
      } else {
        assert.ok(Math.abs(point.evm - csvEvm) < 0.01,
          `${scheme} @ ${point.snr} dB EVM ${point.evm} != measured ${csvEvm}`);
      }
      assert.ok(Math.abs(point.lock - Number(match.carrier_lock)) < 0.001,
        `${scheme} @ ${point.snr} dB lock ${point.lock} != measured ${match.carrier_lock}`);
    }
  }
});

test('FSK carries no EVM, because none is measured for a non-coherent receiver', () => {
  for (const scheme of ['2fsk', '4fsk']) {
    for (const point of EMPIRICAL_ENVELOPE_DATA[scheme]) {
      assert.equal(point.evm, null, `${scheme} @ ${point.snr} dB has an invented EVM`);
    }
  }
});

test('ZERO_ERROR_SNR_THRESHOLDS is the lowest zero-BER SNR in the CSV', async () => {
  const { ZERO_ERROR_SNR_THRESHOLDS, ZERO_ERROR_THRESHOLD_IS_EXACT } =
    await import('./visualizerData.js');
  const rows = readEnvelopeCsv();

  for (const scheme of ['bpsk', 'qpsk', '2fsk', '4fsk', '8psk', '16qam']) {
    const forScheme = rows.filter(r => r.modulation === scheme);
    assert.ok(forScheme.length > 0, `no ${scheme} rows in the CSV`);

    const zeroSnrs = forScheme
      .filter(r => r.measured_ber !== '' && Number(r.measured_ber) === 0)
      .map(r => Number(r.snr_db));
    assert.ok(zeroSnrs.length > 0, `${scheme} never reaches zero measured BER`);
    assert.equal(ZERO_ERROR_SNR_THRESHOLDS[scheme], Math.min(...zeroSnrs),
      `${scheme} threshold does not match the lowest zero-BER SNR measured`);

    // If the lowest SNR ever tested is already error-free, no crossing was
    // observed and the number is only an upper bound.
    const lowestTested = Math.min(...forScheme.map(r => Number(r.snr_db)));
    const crossingObserved = Math.min(...zeroSnrs) > lowestTested;
    assert.equal(ZERO_ERROR_THRESHOLD_IS_EXACT[scheme], crossingObserved,
      `${scheme} is labelled ${ZERO_ERROR_THRESHOLD_IS_EXACT[scheme] ? 'exact' : 'a bound'} but the sweep says otherwise`);
  }
});

test('threshold bar chart marks upper bounds with a <= sign', async () => {
  const { buildThresholdBarChartData, ZERO_ERROR_THRESHOLD_IS_EXACT } =
    await import('./visualizerData.js');
  const { traces } = buildThresholdBarChartData();
  const schemes = ['bpsk', 'qpsk', '2fsk', '4fsk', '8psk', '16qam'];
  schemes.forEach((scheme, i) => {
    const label = traces[0].text[i];
    if (ZERO_ERROR_THRESHOLD_IS_EXACT[scheme] === false) {
      assert.ok(label.startsWith('≤'), `${scheme} bound is not marked: ${label}`);
    } else {
      assert.ok(!label.startsWith('≤'), `${scheme} is exact but marked as a bound: ${label}`);
    }
  });
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
  // Values come from ZERO_ERROR_SNR_THRESHOLDS, which the test above pins to
  // reports/s3_envelope.csv. Restating them literally here is what let three
  // wrong thresholds sit behind a green suite, so read them from the source.
  const { ZERO_ERROR_SNR_THRESHOLDS } = await import('./visualizerData.js');
  assert.deepEqual(trace.y, ['bpsk', 'qpsk', '2fsk', '4fsk', '8psk', '16qam']
    .map(s => ZERO_ERROR_SNR_THRESHOLDS[s]));
  assert.equal(trace.type, 'bar');

  // Verify reference line shape and annotation for current SNR
  assert.equal(chart.layout.shapes.length, 1);
  assert.equal(chart.layout.shapes[0].y0, 12.0);
  assert.equal(chart.layout.annotations.length, 1);
  assert.ok(chart.layout.annotations[0].text.includes('12.0 dB'));
});
