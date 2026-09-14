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

const PRINTABLE = /[\x20-\x7e\r\n\t]/;

/**
 * Nothing in this chain does frame synchronisation, so the Viterbi decode
 * starts mid-message and the first byte is usually a partial one. It is the
 * single non-printing character in an otherwise clean recovery, and rendering
 * it raw puts a replacement glyph at the head of the message.
 *
 * The ASCII view drops those leading bytes and says so; the hex dump and the
 * printable percentage are left exactly as decoded, because that partial byte
 * is a true fact about the recovery and not a display artifact to hide.
 */
function splitLeadingPartial(text) {
  let lead = 0;
  while (lead < text.length && !PRINTABLE.test(text[lead])) lead++;
  return { dropped: lead, body: text.slice(lead) };
}

export default function PayloadViewer({ finalPayload, s6Stage }) {
  const [viewMode, setViewMode] = useState('text'); // 'text' | 'hex'

  const text = finalPayload?.payload_text || s6Stage?.values?.text || '';
  const { dropped, body } = splitLeadingPartial(text);
  const printableFraction = finalPayload?.printable_fraction ?? s6Stage?.values?.printable_fraction ?? 0;
  const looksLikeText = finalPayload?.looks_like_text ?? s6Stage?.values?.looks_like_text ?? false;
  const byteCount = s6Stage?.values?.n_bytes || Math.floor((finalPayload?.bits_count || 0) / 8) || text.length;
  // CCSDS attached sync marker, searched at bit level in S6. A lock means at
  // least two markers at one consistent spacing, so the frame length shown is
  // measured from the stream, not configured.
  const asmLock = Boolean(s6Stage?.values?.asm_lock);
  const asmHits = s6Stage?.values?.asm_hits ?? 0;
  const asmFrameBits = s6Stage?.values?.asm_frame_bits;
  const asmHex = s6Stage?.values?.header_hex || '1ACFFC1D';

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
        {asmLock && (
          <span className="badge badge--ok" title="CCSDS attached sync marker found at bit level">
            ASM LOCK · {asmHex}
          </span>
        )}
        <MetricPill label="Printable" value={`${(printableFraction * 100).toFixed(1)}%`} tone="accent" />
        <MetricPill label="Size" value={`${byteCount} B`} />
        {asmLock && (
          <MetricPill
            label="Frames"
            value={`${asmHits} × ${asmFrameBits ? `${asmFrameBits / 8} B` : '?'}`}
          />
        )}
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
          ? (viewMode === 'hex' ? toHexDump(text) : body)
          : <span style={{ color: 'var(--text-tertiary)' }}>No decoded payload text produced for this run.</span>}
      </div>

      {text && viewMode === 'text' && dropped > 0 && !asmLock && (
        <p style={{ margin: '8px 2px 0', fontSize: 11, lineHeight: 1.5, color: 'var(--text-tertiary)' }}>
          {dropped === 1 ? 'One leading partial byte' : `${dropped} leading partial bytes`} omitted from
          this view. The decode starts mid-message because this capture carries no sync marker for S6
          to frame on. Switch to <strong>HEX DUMP</strong> for the stream exactly as decoded — the
          printable percentage above counts it.
        </p>
      )}
      {asmLock && (
        <p style={{ margin: '8px 2px 0', fontSize: 11, lineHeight: 1.5, color: 'var(--text-tertiary)' }}>
          Framed on the CCSDS attached sync marker: {asmHits} markers every{' '}
          {asmFrameBits ? `${asmFrameBits} bits` : '—'}, found at bit level in the decoded stream. The view
          starts at the first marker. This is sync on a <strong>known</strong> marker, not discovery of
          an unknown frame header.
        </p>
      )}
    </section>
  );
}
