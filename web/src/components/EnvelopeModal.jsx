import React from 'react';
import Modal from './ui/Modal';

export default function EnvelopeModal({ envelope, onClose }) {
  if (!envelope) return null;

  const stages = envelope.stages || {};
  const limits = envelope.limits || {};
  const timeouts = envelope.timeouts || {};

  const globalLimits = [
    { label: 'Stage Timeout', value: `${timeouts.stage_timeout_seconds || 15}s` },
    { label: 'Total Timeout', value: `${timeouts.total_timeout_seconds || 90}s` },
    { label: 'Max Upload Size', value: `${((limits.max_upload_size_bytes || 2147483648) / (1024 * 1024 * 1024)).toFixed(0)} GB` },
  ];

  return (
    <Modal
      title="Operating Envelope Specifications"
      subtitle="Declared pipeline boundaries, timeouts, and signal requirements."
      onClose={onClose}
      maxWidth={680}
    >
      {/* Global Limits */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: 10,
          marginBottom: 20,
        }}
      >
        {globalLimits.map(({ label, value }) => (
          <div key={label} className="inset" style={{ padding: 10 }}>
            <div className="t-label" style={{ fontSize: 9, marginBottom: 3 }}>{label}</div>
            <div className="t-data" style={{ fontSize: 14, fontWeight: 600, color: 'var(--accent-strong)' }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      {/* Stage Specs */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {Object.entries(stages).map(([stgKey, stgSpec]) => (
          <div key={stgKey} className="inset" style={{ padding: '12px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
              <span className="t-section" style={{ fontSize: 12 }}>
                {stgKey.replace('_', ' · ')}
              </span>
              <span className="t-caption" style={{ fontSize: 11 }}>{stgSpec.description || ''}</span>
            </div>
            <div className="t-data" style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.9 }}>
              {Object.entries(stgSpec).filter(([k]) => k !== 'description').map(([k, v]) => {
                let renderedVal = String(v);
                if (Array.isArray(v)) {
                  renderedVal = v.join(', ');
                } else if (typeof v === 'object' && v !== null) {
                  renderedVal = Object.entries(v)
                    .map(([subK, subV]) => `${subK.toUpperCase()}: ${subV} dB`)
                    .join(' | ');
                }
                return (
                  <span key={k} style={{ marginRight: 16, display: 'inline-block' }}>
                    <span style={{ color: 'var(--text-tertiary)' }}>{k}: </span>
                    <span style={{ color: 'var(--text-primary)' }}>{renderedVal}</span>
                  </span>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}
