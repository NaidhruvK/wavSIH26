import React, { useState } from 'react';
import SectionHeader from './ui/SectionHeader';
import MetricPill from './ui/MetricPill';

/**
 * Renders a classic hex dump (offset | bytes | ASCII) from the recovered
 * payload text. Derived directly from the decoded bytes — no synthetic data.
 */
function toHexDump(text, bytesPerRow = 16) {
  const rows = [];
  for (let off = 0; off < text.length; off += bytesPerRow) {
    const chunk = text.slice(off, off + bytesPerRow);
    const hex = Array.from(chunk)
      .map(c => c.charCodeAt(0).toString(16).padStart(2, '0'))
      .join(' ')
      .padEnd(bytesPerRow * 3 - 1, ' ');
    const ascii = Array.from(chunk)
      .map(c => {
        const code = c.charCodeAt(0);
        return code >= 32 && code < 127 ? c : '·';
      })
      .join('');
    rows.push(`${off.toString(16).padStart(6, '0')}  ${hex}  ${ascii}`);
  }
  return rows.join('\n');
}

export default function PayloadViewer({ finalPayload, s6Stage }) {
  const [viewMode, setViewMode] = useState('text'); // 'text' | 'hex'

  const text = finalPayload?.payload_text || s6Stage?.values?.text || '';
  const printableFraction = finalPayload?.printable_fraction ?? s6Stage?.values?.printable_fraction ?? 0;
  const looksLikeText = finalPayload?.looks_like_text ?? s6Stage?.values?.looks_like_text ?? false;
  const byteCount = s6Stage?.values?.n_bytes || Math.floor((finalPayload?.bits_count || 0) / 8) || text.length;

  if (!text && !s6Stage) return null;

  return (
    <section className="panel panel--ticks panel--pad" style={{ marginBottom: 'var(--sp-5)' }}>
      <SectionHeader
        icon="doc"
        title="Recovered Telemetry Payload"
        caption="Stage 6 decoded telemetry stream and character analysis."
      >
        <span className={`badge badge--${looksLikeText ? 'ok' : 'danger'}`}>
          {looksLikeText ? 'VALID TEXT LOCK' : 'BINARY / RANDOM'}
        </span>
        <MetricPill label="Printable" value={`${(printableFraction * 100).toFixed(1)}%`} tone="accent" />
        <MetricPill label="Size" value={`${byteCount} B`} />
      </SectionHeader>

      {/* View mode switcher (only meaningful when payload exists) */}
      {text && (
        <div role="tablist" aria-label="Payload view mode" style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
          <button
            role="tab"
            aria-selected={viewMode === 'text'}
            onClick={() => setViewMode('text')}
            className={`tab-btn${viewMode === 'text' ? ' is-active' : ''}`}
          >
            ASCII TEXT
          </button>
          <button
            role="tab"
            aria-selected={viewMode === 'hex'}
            onClick={() => setViewMode('hex')}
            className={`tab-btn${viewMode === 'hex' ? ' is-active' : ''}`}
          >
            HEX DUMP
          </button>
        </div>
      )}

      {/* Payload Display */}
      <div
        className="inset t-data"
        style={{
          padding: 16,
          fontSize: viewMode === 'hex' ? 11 : 13,
          color: 'var(--text-primary)',
          minHeight: 80,
          maxHeight: 260,
          overflowY: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: viewMode === 'hex' ? 'normal' : 'break-all',
          lineHeight: 1.7,
        }}
      >
        {text
          ? (viewMode === 'hex' ? toHexDump(text) : text)
          : <span style={{ color: 'var(--text-tertiary)' }}>No decoded payload text produced for this run.</span>}
      </div>
    </section>
  );
}
