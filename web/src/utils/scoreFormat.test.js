import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  formatScore,
  formatFractionOrNumber,
  scoresArePercent,
  SCORE_KINDS,
} from './scoreFormat.js';
import { parseHypothesesData } from './visualizerData.js';

const PERCENT = /(-?\d+(?:\.\d+)?)%/;

function assertNoPercentOutsideRange(text) {
  const m = PERCENT.exec(text);
  if (m) {
    const v = Number(m[1]);
    assert.ok(v >= 0 && v <= 100, `"${text}" shows a percent outside 0-100`);
  }
}

test('S3 search prior above 1 is a named number, never 121%', () => {
  const out = formatScore(1.21, 's3_receive');
  assert.equal(out, 'prior 1.21');
  assertNoPercentOutsideRange(out);
});

test('S4 rank score is a named number even when inside 0..1', () => {
  // the correct interleaver at span 14 scores 1/15 and used to read "7%"
  const out = formatScore(1 / 15, 's4_recover');
  assert.equal(out, 'rank score 0.067');
  assert.ok(!out.includes('%'));
});

test('fraction stages keep percent while in range', () => {
  assert.equal(formatScore(0.87, 's2_estimate'), '87%');
  assert.equal(formatScore(1, 's5_decode'), '100%');
  assert.equal(formatScore(0, 's6_frame'), '0%');
});

test('a fraction stage that emits an out-of-range value falls back to a named number', () => {
  assert.equal(formatScore(1.4, 's2_estimate'), 'class probability 1.4');
  assert.equal(formatScore(-0.2, 's6_frame'), 'printable fraction -0.2');
  assert.equal(formatScore(NaN, 's1_detect'), 'confidence NaN');
});

test('no stage, no value, produces a percent outside 0..100', () => {
  const samples = [-5, -1, -0.01, 0, 0.004, 0.07, 0.5, 0.999, 1, 1.0001, 1.21, 7, 250, Infinity, NaN];
  for (const stage of [...Object.keys(SCORE_KINDS), 'unknown_stage']) {
    for (const s of samples) assertNoPercentOutsideRange(formatScore(s, stage));
  }
  for (const s of samples) assertNoPercentOutsideRange(formatFractionOrNumber(s));
});

test('a chart axis is percent only when the stage is a fraction and every score is in range', () => {
  assert.equal(scoresArePercent('s2_estimate', [0.1, 0.9]), true);
  assert.equal(scoresArePercent('s2_estimate', [0.1, 1.2]), false);
  assert.equal(scoresArePercent('s3_receive', [0.1, 0.2]), false);
  assert.equal(scoresArePercent('s4_recover', [0.067]), false);
});

test('parseHypothesesData leaves S3 and S4 scores unscaled and says so', () => {
  const s3 = parseHypothesesData([{ value: 'qpsk', score: 1.21 }, { value: 'bpsk', score: 0.3 }], 's3_receive');
  assert.equal(s3.isPercent, false);
  assert.deepEqual(s3.scores, [0.3, 1.21]);
  assert.equal(s3.axisTitle, 'prior');

  const s2 = parseHypothesesData([{ value: 'qpsk', score: 0.92 }], 's2_estimate');
  assert.equal(s2.isPercent, true);
  assert.deepEqual(s2.scores, [92]);
});
