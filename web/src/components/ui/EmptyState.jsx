import React from 'react';
import Icon from './icons';

/**
 * Consistent empty / unavailable state for plots and data panels.
 */
export default function EmptyState({ icon = 'waveform', title, children }) {
  return (
    <div
      className="inset"
      style={{ padding: '40px 20px', textAlign: 'center' }}
    >
      <div style={{ color: 'var(--text-tertiary)', marginBottom: 10 }}>
        <Icon name={icon} size={24} />
      </div>
      <div className="t-section" style={{ fontSize: 12, marginBottom: 6 }}>
        {title}
      </div>
      <div className="t-caption" style={{ maxWidth: 520, margin: '0 auto', lineHeight: 1.6 }}>
        {children}
      </div>
    </div>
  );
}
