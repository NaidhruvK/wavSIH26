import React from 'react';
import { getArtifactUrl } from '../api';
import StatusBadge, { statusTone } from './ui/StatusBadge';
import Icon from './ui/icons';

const STAGE_META = {
  s0_ingest:   { idx: 'S0', title: 'INGEST',   desc: 'WAV/IQ Normalization & Sniffer' },
  s1_detect:   { idx: 'S1', title: 'DETECT',   desc: 'Spectral Energy & SNR Analysis' },
  s2_estimate: { idx: 'S2', title: 'ESTIMATE', desc: 'Symbol Rate & Carrier Offset' },
  s3_receive:  { idx: 'S3', title: 'RECEIVE',  desc: 'Demodulation & Soft LLRs' },
  s4_recover:  { idx: 'S4', title: 'RECOVER',  desc: 'Rank-Collapse Coding Recovery' },
  s5_decode:   { idx: 'S5', title: 'DECODE',   desc: 'Viterbi / FEC Error Correction' },
  s6_frame:    { idx: 'S6', title: 'FRAME',    desc: 'Telemetry & Payload Extraction' },
};

const TONE_COLOR = {
  ok: 'var(--ok)',
  warn: 'var(--warn)',
  danger: 'var(--danger)',
  accent: 'var(--accent)',
  neutral: 'var(--text-tertiary)',
};

/**
 * Human-readable rendering for stage values. Nested objects/arrays are
 * compacted instead of degrading to "[object Object]".
 */
function formatValue(v, depth = 0) {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (Array.isArray(v)) {
    if (depth >= 1) return `[${v.length}]`;
    return v.slice(0, 3).map(item => formatValue(item, depth + 1)).join(', ') + (v.length > 3 ? ` +${v.length - 3}` : '');
  }
  if (typeof v === 'object') {
    if (depth >= 1) return '{…}';
    const entries = Object.entries(v).slice(0, 3);
    const body = entries.map(([k, val]) => `${k}: ${formatValue(val, depth + 1)}`).join(' · ');
    return Object.keys(v).length > 3 ? `${body} …` : body;
  }
  const s = String(v);
  return s.length > 48 ? `${s.slice(0, 45)}…` : s;
}

/**
 * The artifact endpoint serves files by stored basename (e.g. "psd" from
 * reports/artifacts/<run>/psd.json), not by the stage's artifact key.
 */
function artifactServedName(key, declaredPath) {
  if (typeof declaredPath === 'string' && declaredPath) {
    const base = declaredPath.split(/[\\/]/).pop();
    if (base) return base.replace(/\.json$/i, '');
  }
  return key;
}

export default function StageCard({ stageName, stageResult, runId }) {
  const meta = STAGE_META[stageName] || { idx: '—', title: stageName.toUpperCase(), desc: 'Pipeline Stage' };
  const isPresent = Boolean(stageResult);
  const status = stageResult?.status || 'pending';
  const confidence = stageResult?.confidence ?? 0;
  const elapsedMs = stageResult?.elapsed_ms ?? 0;
  const values = stageResult?.values || {};
  const hypotheses = stageResult?.hypotheses || [];
  const artifacts = stageResult?.artifacts || {};
  const reason = stageResult?.reason;

  const tone = statusTone(status);
  const toneColor = TONE_COLOR[tone] || TONE_COLOR.neutral;

  return (
    <article
      className="panel"
      aria-label={`Stage ${meta.idx} ${meta.title}: ${status}`}
      style={{
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        opacity: isPresent ? 1 : 0.55,
        borderLeft: `2px solid ${isPresent ? toneColor : 'var(--border)'}`,
        transition: 'opacity 0.25s ease, border-color 0.25s ease',
      }}
    >
      <div>
        {/* Stage Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10, gap: 8 }}>
          <div style={{ display: 'flex', gap: 10 }}>
            <span
              className="t-data"
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: isPresent ? 'var(--accent-strong)' : 'var(--text-tertiary)',
                border: '1px solid var(--border-strong)',
                borderRadius: 'var(--radius-sm)',
                padding: '2px 6px',
                lineHeight: '16px',
                flexShrink: 0,
              }}
            >
              {meta.idx}
            </span>
            <div>
              <div className="t-section" style={{ fontSize: 12 }}>{meta.title}</div>
              <div className="t-caption" style={{ fontSize: 11, marginTop: 1 }}>{meta.desc}</div>
            </div>
          </div>
          <StatusBadge status={status} />
        </div>

        {/* Confidence Meter */}
        {isPresent && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
              <span className="t-label" style={{ fontSize: 9 }}>Confidence</span>
              <span className="t-data" style={{ fontSize: 11, fontWeight: 600, color: toneColor }}>
                {(confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div
              role="progressbar"
              aria-valuenow={Math.round(confidence * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${meta.title} confidence`}
              style={{ width: '100%', height: 3, background: 'var(--surface-inset)', borderRadius: 1, overflow: 'hidden' }}
            >
              <div
                style={{
                  width: `${Math.min(Math.max(confidence * 100, 0), 100)}%`,
                  height: '100%',
                  background: toneColor,
                  transition: 'width 0.3s ease',
                }}
              />
            </div>
          </div>
        )}

        {/* Key Values */}
        {isPresent && Object.keys(values).length > 0 && (
          <div className="inset" style={{ padding: '8px 10px', fontSize: 11, marginBottom: 10 }}>
            {Object.entries(values).slice(0, 4).map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '2px 0' }}>
                <span style={{ color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  {k.replace(/_/g, ' ')}
                </span>
                <span className="t-data" style={{ fontSize: 11, fontWeight: 600, textAlign: 'right', wordBreak: 'break-word' }}>
                  {formatValue(v)}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Hypotheses Preview */}
        {isPresent && hypotheses.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            <div className="t-label" style={{ fontSize: 9, marginBottom: 4 }}>
              Ranked Hypotheses
            </div>
            {hypotheses.slice(0, 2).map((h, i) => (
              <div
                key={i}
                className="t-data"
                style={{ fontSize: 11, display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}
              >
                <span style={{ color: i === 0 ? 'var(--accent-strong)' : 'var(--text-secondary)' }}>
                  {formatValue(h.value ?? h)}
                </span>
                {h.score !== undefined && (
                  <span style={{ color: 'var(--text-tertiary)' }}>{(h.score * 100).toFixed(0)}%</span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Error / Reason Callout */}
        {reason && (
          <div
            style={{
              fontSize: 11,
              color: 'var(--danger)',
              background: 'var(--danger-dim)',
              border: '1px solid var(--danger-border)',
              padding: '6px 8px',
              borderRadius: 'var(--radius-sm)',
              marginBottom: 10,
              wordBreak: 'break-word',
              lineHeight: 1.5,
            }}
          >
            {reason}
          </div>
        )}
      </div>

      {/* Footer: elapsed + artifacts */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
          paddingTop: 8,
          borderTop: '1px solid var(--border)',
        }}
      >
        <span className="t-data" style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>
          {isPresent ? `${elapsedMs.toFixed(1)} ms` : '——'}
        </span>

        {Object.keys(artifacts).length > 0 && runId && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {Object.entries(artifacts).map(([artKey, artPath]) => (
              <a
                key={artKey}
                href={getArtifactUrl(runId, artifactServedName(artKey, artPath))}
                target="_blank"
                rel="noreferrer"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  color: 'var(--accent-strong)',
                  textDecoration: 'none',
                  fontSize: 10,
                  fontFamily: 'var(--font-mono)',
                  background: 'var(--accent-dim)',
                  border: '1px solid transparent',
                  padding: '2px 6px',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                <Icon name="external" size={10} />
                {artKey.replace(/_/g, ' ')}
              </a>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
