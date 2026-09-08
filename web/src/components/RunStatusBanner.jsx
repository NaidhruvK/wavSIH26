import React from 'react';

export default function RunStatusBanner({ runId, report, isPolling, onReset }) {
  if (!runId && !report) return null;

  const status = report?.status || (isPolling ? 'running' : 'completed');
  const verdict = report?.envelope_verdict || 'pending';
  const fileMeta = report?.file_meta || {};

  const getStatusColor = (st) => {
    switch (st?.toLowerCase()) {
      case 'completed': return 'var(--emerald)';
      case 'running': return 'var(--cyan)';
      case 'queued': return 'var(--amber)';
      case 'failed': return 'var(--rose)';
      default: return 'var(--text-dim)';
    }
  };

  const getVerdictBadge = (vd) => {
    switch (vd?.toLowerCase()) {
      case 'in_envelope':
        return { bg: 'rgba(16, 185, 129, 0.1)', color: 'var(--emerald)', border: 'rgba(16, 185, 129, 0.3)', label: 'IN ENVELOPE' };
      case 'out_of_envelope':
        return { bg: 'rgba(245, 158, 11, 0.1)', color: 'var(--amber)', border: 'rgba(245, 158, 11, 0.3)', label: 'OUT OF ENVELOPE' };
      case 'failed':
        return { bg: 'rgba(244, 63, 94, 0.1)', color: 'var(--rose)', border: 'rgba(244, 63, 94, 0.3)', label: 'FAILED' };
      default:
        return { bg: 'rgba(100, 116, 139, 0.1)', color: 'var(--text-muted)', border: 'var(--border)', label: vd.toUpperCase() };
    }
  };

  const verdictStyle = getVerdictBadge(verdict);

  const copyRunId = () => {
    if (runId) {
      navigator.clipboard.writeText(runId);
    }
  };

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: '12px',
      padding: '16px 20px',
      marginBottom: '24px',
      display: 'flex',
      flexWrap: 'wrap',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: '16px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
        <div>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontWeight: 600, display: 'block' }}>
            ACTIVE RUN ID
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '14px', color: '#fff' }}>
              {runId || report?.run_id || '—'}
            </span>
            {runId && (
              <button
                onClick={copyRunId}
                title="Copy Run ID"
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-dim)',
                  cursor: 'pointer',
                  fontSize: '12px',
                  padding: '2px 4px',
                }}
              >
                📋
              </button>
            )}
          </div>
        </div>

        {/* Status Pill */}
        <div>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontWeight: 600, display: 'block' }}>
            EXECUTION STATUS
          </span>
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '12px',
            fontWeight: 700,
            color: getStatusColor(status),
            fontFamily: 'var(--font-mono)',
          }}>
            {isPolling && <span className="spin-anim" style={{ display: 'inline-block' }}>⟳</span>}
            <span>{status.toUpperCase()}</span>
          </div>
        </div>

        {/* Verdict Pill */}
        <div>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontWeight: 600, display: 'block' }}>
            ENVELOPE VERDICT
          </span>
          <span style={{
            display: 'inline-block',
            padding: '2px 8px',
            borderRadius: '4px',
            fontSize: '11px',
            fontWeight: 700,
            background: verdictStyle.bg,
            color: verdictStyle.color,
            border: `1px solid ${verdictStyle.border}`,
            fontFamily: 'var(--font-mono)',
          }}>
            {verdictStyle.label}
          </span>
        </div>

        {/* Filename details */}
        {fileMeta.filename && (
          <div>
            <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontWeight: 600, display: 'block' }}>
              SOURCE FILE
            </span>
            <span style={{ fontSize: '13px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {fileMeta.filename} ({((fileMeta.size_bytes || 0) / 1024).toFixed(1)} KB)
            </span>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {onReset && (
          <button
            onClick={onReset}
            style={{
              background: 'var(--bg-input)',
              border: '1px solid var(--border)',
              color: 'var(--text-muted)',
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            New Analysis
          </button>
        )}
      </div>
    </div>
  );
}
