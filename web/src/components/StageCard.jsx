import React from 'react';
import { getArtifactUrl } from '../api';

const STAGE_META = {
  s0_ingest: { title: 'S0 • INGEST', desc: 'WAV/IQ Normalization & Sniffer' },
  s1_detect: { title: 'S1 • DETECT', desc: 'Spectral Energy & SNR Analysis' },
  s2_estimate: { title: 'S2 • ESTIMATE', desc: 'Symbol Rate & Carrier Offset' },
  s3_receive: { title: 'S3 • RECEIVE', desc: 'Demodulation & Soft LLRs' },
  s4_recover: { title: 'S4 • RECOVER', desc: 'Rank-Collapse Coding Recovery' },
  s5_decode: { title: 'S5 • DECODE', desc: 'Viterbi / FEC Error Correction' },
  s6_frame: { title: 'S6 • FRAME', desc: 'Telemetry & Payload Extraction' },
};

export default function StageCard({ stageName, stageResult, runId }) {
  const meta = STAGE_META[stageName] || { title: stageName.toUpperCase(), desc: 'Pipeline Stage' };
  const isPresent = Boolean(stageResult);
  const status = stageResult?.status || 'pending';
  const confidence = stageResult?.confidence ?? 0;
  const elapsedMs = stageResult?.elapsed_ms ?? 0;
  const values = stageResult?.values || {};
  const hypotheses = stageResult?.hypotheses || [];
  const artifacts = stageResult?.artifacts || {};
  const reason = stageResult?.reason;

  const getStatusBadge = () => {
    switch (status.toLowerCase()) {
      case 'ok':
        return { color: 'var(--emerald)', bg: 'rgba(16, 185, 129, 0.1)', text: 'OK' };
      case 'low_confidence':
        return { color: 'var(--amber)', bg: 'rgba(245, 158, 11, 0.1)', text: 'LOW CONF' };
      case 'failed':
        return { color: 'var(--rose)', bg: 'rgba(244, 63, 94, 0.1)', text: 'FAILED' };
      case 'out_of_envelope':
        return { color: 'var(--amber)', bg: 'rgba(245, 158, 11, 0.1)', text: 'OUT OF ENVELOPE' };
      default:
        return { color: 'var(--text-dim)', bg: 'rgba(100, 116, 139, 0.08)', text: 'PENDING' };
    }
  };

  const badge = getStatusBadge();

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: `1px solid ${status === 'ok' ? 'rgba(16, 185, 129, 0.2)' : status === 'failed' ? 'rgba(244, 63, 94, 0.2)' : 'var(--border)'}`,
      borderRadius: '10px',
      padding: '16px',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
      boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
      opacity: isPresent ? 1 : 0.6,
      transition: 'all 0.2s ease',
    }}>
      {/* Stage Header */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
          <div>
            <div style={{ fontSize: '13px', fontWeight: 800, letterSpacing: '0.5px', color: '#fff' }}>
              {meta.title}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '1px' }}>
              {meta.desc}
            </div>
          </div>
          <span style={{
            fontSize: '10px',
            fontWeight: 700,
            fontFamily: 'var(--font-mono)',
            padding: '2px 6px',
            borderRadius: '4px',
            color: badge.color,
            background: badge.bg,
            border: `1px solid ${badge.color}44`,
          }}>
            {badge.text}
          </span>
        </div>

        {/* Confidence Meter */}
        {isPresent && (
          <div style={{ marginBottom: '12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '3px' }}>
              <span style={{ color: 'var(--text-dim)' }}>Confidence</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: badge.color }}>
                {(confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div style={{ width: '100%', height: '4px', background: 'var(--bg-input)', borderRadius: '2px', overflow: 'hidden' }}>
              <div style={{
                width: `${Math.min(Math.max(confidence * 100, 0), 100)}%`,
                height: '100%',
                background: badge.color,
                transition: 'width 0.3s ease',
              }} />
            </div>
          </div>
        )}

        {/* Key Values / Metrics Grid */}
        {isPresent && Object.keys(values).length > 0 && (
          <div style={{
            background: 'var(--bg-input)',
            borderRadius: '6px',
            padding: '8px 10px',
            fontSize: '11px',
            marginBottom: '10px',
          }}>
            {Object.entries(values).slice(0, 4).map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                <span style={{ color: 'var(--text-dim)' }}>{k.replace(/_/g, ' ')}:</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: '#fff', fontWeight: 600 }}>
                  {typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : String(v)}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Hypotheses Preview */}
        {isPresent && hypotheses.length > 0 && (
          <div style={{ marginBottom: '10px' }}>
            <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-dim)', marginBottom: '4px', textTransform: 'uppercase' }}>
              Ranked Hypotheses
            </div>
            {hypotheses.slice(0, 2).map((h, i) => (
              <div key={i} style={{
                fontSize: '11px',
                display: 'flex',
                justifyContent: 'space-between',
                padding: '2px 0',
                fontFamily: 'var(--font-mono)',
              }}>
                <span style={{ color: 'var(--cyan)' }}>{String(h.value || h)}</span>
                {h.score !== undefined && (
                  <span style={{ color: 'var(--text-dim)' }}>{(h.score * 100).toFixed(0)}%</span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Error / Reason Callout */}
        {reason && (
          <div style={{
            fontSize: '11px',
            color: 'var(--rose)',
            background: 'rgba(244, 63, 94, 0.08)',
            border: '1px solid rgba(244, 63, 94, 0.2)',
            padding: '6px 8px',
            borderRadius: '4px',
            marginBottom: '10px',
            wordBreak: 'break-word',
          }}>
            {reason}
          </div>
        )}
      </div>

      {/* Footer: Elapsed time & Artifacts */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingTop: '8px',
        borderTop: '1px solid var(--border)',
        fontSize: '11px',
        color: 'var(--text-dim)',
      }}>
        <span>{isPresent ? `${elapsedMs.toFixed(1)} ms` : '—'}</span>

        {/* Artifact Links */}
        {Object.keys(artifacts).length > 0 && runId && (
          <div style={{ display: 'flex', gap: '6px' }}>
            {Object.keys(artifacts).map(artKey => (
              <a
                key={artKey}
                href={getArtifactUrl(runId, artKey)}
                target="_blank"
                rel="noreferrer"
                style={{
                  color: 'var(--cyan)',
                  textDecoration: 'none',
                  fontSize: '10px',
                  fontWeight: 600,
                  background: 'rgba(6, 182, 212, 0.08)',
                  padding: '2px 6px',
                  borderRadius: '3px',
                }}
              >
                📊 {artKey.replace(/_/g, ' ')}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
