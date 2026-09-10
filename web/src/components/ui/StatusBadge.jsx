import React from 'react';

/**
 * Single source of truth for pipeline status → visual semantics.
 * Used by stage cards, run banner, envelope views, and payload viewer.
 */

const STATUS_MAP = {
  ok:              { tone: 'ok',      label: 'OK' },
  completed:       { tone: 'ok',      label: 'COMPLETED' },
  in_envelope:     { tone: 'ok',      label: 'IN ENVELOPE' },
  running:         { tone: 'accent',  label: 'RUNNING' },
  queued:          { tone: 'warn',    label: 'QUEUED' },
  low_confidence:  { tone: 'warn',    label: 'LOW CONF' },
  out_of_envelope: { tone: 'warn',    label: 'OUT OF ENVELOPE' },
  failed:          { tone: 'danger',  label: 'FAILED' },
  pending:         { tone: 'neutral', label: 'PENDING' },
};

export function statusTone(status) {
  return (STATUS_MAP[String(status || '').toLowerCase()] || { tone: 'neutral' }).tone;
}

export default function StatusBadge({ status, label, withLed = false, pulse = false }) {
  const key = String(status || 'pending').toLowerCase();
  const spec = STATUS_MAP[key] || { tone: 'neutral', label: key.replace(/_/g, ' ').toUpperCase() };
  return (
    <span className={`badge badge--${spec.tone}`}>
      {withLed && <span className={`led led--${spec.tone}${pulse ? ' led--pulse' : ''}`} />}
      {label || spec.label}
    </span>
  );
}
