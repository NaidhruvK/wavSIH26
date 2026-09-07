import React from 'react';

export default function EnvelopeModal({ envelope, onClose }) {
  if (!envelope) return null;

  const stages = envelope.stages || {};
  const limits = envelope.limits || {};
  const timeouts = envelope.timeouts || {};

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0, 0, 0, 0.75)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 50,
      padding: '20px',
    }}>
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: '12px',
        width: '100%',
        maxWidth: '680px',
        maxHeight: '85vh',
        overflowY: 'auto',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.5)',
        padding: '24px',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <h2 style={{ fontSize: '16px', fontWeight: 800, color: '#fff' }}>
              OPERATING ENVELOPE SPECIFICATIONS
            </h2>
            <p style={{ fontSize: '12px', color: 'var(--text-dim)' }}>
              Declared pipeline boundaries, timeouts, and signal requirements.
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-dim)',
              fontSize: '20px',
              cursor: 'pointer',
            }}
          >
            ✕
          </button>
        </div>

        {/* Global Limits */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: '10px',
          marginBottom: '20px',
        }}>
          <div style={{ background: 'var(--bg-input)', padding: '10px', borderRadius: '6px', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontWeight: 600 }}>STAGE TIMEOUT</div>
            <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--cyan)', fontFamily: 'var(--font-mono)' }}>
              {timeouts.stage_timeout_seconds || 15}s
            </div>
          </div>
          <div style={{ background: 'var(--bg-input)', padding: '10px', borderRadius: '6px', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontWeight: 600 }}>TOTAL TIMEOUT</div>
            <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--cyan)', fontFamily: 'var(--font-mono)' }}>
              {timeouts.total_timeout_seconds || 90}s
            </div>
          </div>
          <div style={{ background: 'var(--bg-input)', padding: '10px', borderRadius: '6px', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontWeight: 600 }}>MAX UPLOAD SIZE</div>
            <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--cyan)', fontFamily: 'var(--font-mono)' }}>
              {((limits.max_upload_size_bytes || 2147483648) / (1024 * 1024 * 1024)).toFixed(0)} GB
            </div>
          </div>
        </div>

        {/* Stage Specs */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {Object.entries(stages).map(([stgKey, stgSpec]) => (
            <div
              key={stgKey}
              style={{
                background: 'var(--bg-input)',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                padding: '12px 16px',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                <span style={{ fontWeight: 800, fontSize: '13px', color: '#fff', textTransform: 'uppercase' }}>
                  {stgKey.replace('_', ' • ')}
                </span>
                <span style={{ fontSize: '11px', color: 'var(--text-dim)' }}>{stgSpec.description || ''}</span>
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
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
                    <span key={k} style={{ marginRight: '16px', display: 'inline-block' }}>
                      <span style={{ color: 'var(--text-dim)' }}>{k}: </span>
                      <span style={{ color: '#fff' }}>{renderedVal}</span>
                    </span>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: '20px', textAlign: 'right' }}>
          <button
            onClick={onClose}
            style={{
              background: 'var(--bg-input)',
              border: '1px solid var(--border)',
              color: '#fff',
              padding: '8px 18px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
