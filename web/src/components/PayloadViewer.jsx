import React, { useState } from 'react';

export default function PayloadViewer({ finalPayload, s6Stage }) {
  const [viewMode, setViewMode] = useState('text'); // 'text' | 'raw'

  const text = finalPayload?.payload_text || s6Stage?.values?.text || '';
  const printableFraction = finalPayload?.printable_fraction ?? s6Stage?.values?.printable_fraction ?? 0;
  const looksLikeText = finalPayload?.looks_like_text ?? s6Stage?.values?.looks_like_text ?? false;
  const byteCount = s6Stage?.values?.n_bytes || Math.floor((finalPayload?.bits_count || 0) / 8) || text.length;

  if (!text && !s6Stage) return null;

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: '12px',
      padding: '20px',
      marginBottom: '24px',
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '16px',
        flexWrap: 'wrap',
        gap: '10px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '18px' }}>📜</span>
          <div>
            <h3 style={{ fontSize: '15px', fontWeight: 800, color: '#fff' }}>
              RECOVERED TELEMETRY PAYLOAD
            </h3>
            <span style={{ fontSize: '12px', color: 'var(--text-dim)' }}>
              Stage 6 decoded telemetry stream and character analysis
            </span>
          </div>
        </div>

        {/* Metrics Pills */}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span style={{
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            padding: '3px 8px',
            borderRadius: '4px',
            background: looksLikeText ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)',
            color: looksLikeText ? 'var(--emerald)' : 'var(--rose)',
            border: `1px solid ${looksLikeText ? 'rgba(16, 185, 129, 0.3)' : 'rgba(244, 63, 94, 0.3)'}`,
            fontWeight: 700,
          }}>
            {looksLikeText ? 'VALID TEXT LOCK' : 'BINARY / RANDOM'}
          </span>

          <span style={{
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            padding: '3px 8px',
            borderRadius: '4px',
            background: 'var(--bg-input)',
            color: 'var(--cyan)',
            border: '1px solid var(--border)',
          }}>
            PRINTABLE: {(printableFraction * 100).toFixed(1)}%
          </span>

          <span style={{
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            padding: '3px 8px',
            borderRadius: '4px',
            background: 'var(--bg-input)',
            color: 'var(--text-muted)',
            border: '1px solid var(--border)',
          }}>
            SIZE: {byteCount} BYTES
          </span>
        </div>
      </div>

      {/* Payload Display Box */}
      <div style={{
        background: 'var(--bg-main)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        padding: '16px',
        fontFamily: 'var(--font-mono)',
        fontSize: '13px',
        color: '#e2e8f0',
        minHeight: '80px',
        maxHeight: '240px',
        overflowY: 'auto',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
        lineHeight: 1.6,
      }}>
        {text || <span style={{ color: 'var(--text-dim)' }}>No decoded payload text produced for this run.</span>}
      </div>
    </div>
  );
}
