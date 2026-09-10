import React from 'react';

const TONE_COLORS = {
  ok: 'var(--ok)',
  warn: 'var(--warn)',
  danger: 'var(--danger)',
  accent: 'var(--accent-strong)',
  default: 'var(--text-primary)',
  muted: 'var(--text-tertiary)',
};

/**
 * Compact label→value readout used under charts and in summary rows.
 */
export default function MetricPill({ label, value, tone = 'default', style = {} }) {
  return (
    <span className="metric-pill" style={style}>
      <span className="mp-label">{label}</span>
      <span className="mp-value" style={{ color: TONE_COLORS[tone] || TONE_COLORS.default }}>
        {value}
      </span>
    </span>
  );
}
