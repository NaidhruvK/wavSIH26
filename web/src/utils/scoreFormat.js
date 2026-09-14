/**
 * What a hypothesis `score` means, per stage - and therefore whether it may be
 * printed as a percent.
 *
 * Every hypothesis used to render as `(score * 100)%`. That is only honest for
 * scores that are fractions of something. Three stages emit scores that are
 * not:
 *
 *   S3  the search-order prior  mp * (0.1 + rs) * (0.1 + cs)  (search.py), which
 *       tops out at 1.21 - rendered "121%".
 *   S4  a ranking key  1 / (1 + span)  (rank_collapse.recover_interleaver), so
 *       the CORRECT interleaver at span 14 rendered "7%", which reads as
 *       "almost certainly wrong".
 *   S0  a sniffer plausibility score, not a probability.
 *
 * Those print as a named number ("prior 1.21", "rank score 0.067"). The rest
 * are fractions and keep the percent, but only while the value is actually in
 * [0, 1]; anything outside that prints as a named number whatever the stage
 * claims, so no percent outside 0-100 can ever reach the screen.
 */

export const SCORE_KINDS = {
  s0_ingest: { kind: 'metric', label: 'sniffer score' },
  s1_detect: { kind: 'fraction', label: 'confidence' },
  s2_estimate: { kind: 'fraction', label: 'class probability' },
  s3_receive: { kind: 'metric', label: 'prior' },
  s4_recover: { kind: 'metric', label: 'rank score' },
  s5_decode: { kind: 'fraction', label: 'confidence' },
  s6_frame: { kind: 'fraction', label: 'printable fraction' },
};

const UNKNOWN_STAGE = { kind: 'fraction', label: 'score' };

export function isUnitInterval(x) {
  return typeof x === 'number' && Number.isFinite(x) && x >= 0 && x <= 1;
}

function trimNumber(x) {
  if (typeof x !== 'number' || !Number.isFinite(x)) return String(x);
  const abs = Math.abs(x);
  if (abs !== 0 && abs < 0.01) return x.toExponential(1);
  if (abs < 1) return x.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
  return x.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

/**
 * Whether a whole set of scores from one stage may be drawn as percentages.
 * One out-of-range score disqualifies the set: a chart axis cannot be percent
 * for some bars and not others.
 */
export function scoresArePercent(stageName, scores) {
  const meta = SCORE_KINDS[stageName] || UNKNOWN_STAGE;
  if (meta.kind !== 'fraction') return false;
  return (scores || []).every(isUnitInterval);
}

export function scoreLabel(stageName) {
  return (SCORE_KINDS[stageName] || UNKNOWN_STAGE).label;
}

/**
 * One score as text: "87%" for an in-range fraction, otherwise
 * "<label> <number>".
 */
export function formatScore(score, stageName) {
  const meta = SCORE_KINDS[stageName] || UNKNOWN_STAGE;
  if (meta.kind === 'fraction' && isUnitInterval(score)) {
    return `${(score * 100).toFixed(0)}%`;
  }
  return `${meta.label} ${trimNumber(score)}`;
}

/** A 0..1 metric as a percent, or the raw number when it is not in 0..1. */
export function formatFractionOrNumber(x, digits = 1) {
  if (isUnitInterval(x)) return `${(x * 100).toFixed(digits)}%`;
  return trimNumber(x);
}
