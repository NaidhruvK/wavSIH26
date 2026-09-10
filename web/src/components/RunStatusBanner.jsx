import React, { useState } from 'react';
import Icon from './ui/icons';
import StatusBadge from './ui/StatusBadge';

const RAIL_STAGES = [
  { key: 's0_ingest', short: 'S0' },
  { key: 's1_detect', short: 'S1' },
  { key: 's2_estimate', short: 'S2' },
  { key: 's3_receive', short: 'S3' },
  { key: 's4_recover', short: 'S4' },
  { key: 's5_decode', short: 'S5' },
  { key: 's6_frame', short: 'S6' },
];

function railTone(stageResult, isActive) {
  if (isActive) return 'active';
  if (!stageResult) return '';
  switch (String(stageResult.status || '').toLowerCase()) {
    case 'ok': return 'ok';
    case 'low_confidence':
    case 'out_of_envelope': return 'warn';
    case 'failed': return 'danger';
    default: return '';
  }
}

export default function RunStatusBanner({ runId, report, isPolling, onReset }) {
  const [copied, setCopied] = useState(false);

  if (!runId && !report) return null;

  const status = report?.status || (isPolling ? 'running' : 'completed');
  const verdict = report?.envelope_verdict || 'pending';
  const fileMeta = report?.file_meta || {};

  const stageMap = {};
  (report?.stages || []).forEach(s => { stageMap[s.stage] = s; });

  // The active stage is the first unreported stage while the run is live.
  const firstMissingIdx = RAIL_STAGES.findIndex(s => !stageMap[s.key]);
  const activeIdx = isPolling && firstMissingIdx !== -1 ? firstMissingIdx : -1;

  const copyRunId = async () => {
    if (!runId) return;
    try {
      await navigator.clipboard.writeText(runId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard unavailable — ignore silently
    }
  };

  return (
    <section
      className="panel panel--ticks enter-anim"
      aria-label="Active run status"
      style={{ padding: '14px 18px', marginBottom: 'var(--sp-5)' }}
    >
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 'var(--sp-4)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-6)', flexWrap: 'wrap', rowGap: 'var(--sp-3)' }}>
          <div>
            <span className="t-label" style={{ display: 'block', marginBottom: 3 }}>
              Active Run ID
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="t-data" style={{ fontWeight: 600, fontSize: 13 }}>
                {runId || report?.run_id || '—'}
              </span>
              {runId && (
                <button
                  onClick={copyRunId}
                  className="btn btn--ghost btn--icon"
                  aria-label="Copy run ID"
                  title="Copy Run ID"
                  style={{ color: copied ? 'var(--ok)' : 'var(--text-tertiary)' }}
                >
                  <Icon name={copied ? 'check' : 'copy'} size={13} />
                </button>
              )}
            </div>
          </div>

          <div>
            <span className="t-label" style={{ display: 'block', marginBottom: 3 }}>
              Execution Status
            </span>
            <StatusBadge status={status} withLed pulse={isPolling} />
          </div>

          <div>
            <span className="t-label" style={{ display: 'block', marginBottom: 3 }}>
              Envelope Verdict
            </span>
            <StatusBadge status={verdict} />
          </div>

          {fileMeta.filename && (
            <div>
              <span className="t-label" style={{ display: 'block', marginBottom: 3 }}>
                Source File
              </span>
              <span className="t-data" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                {fileMeta.filename} · {((fileMeta.size_bytes || 0) / 1024).toFixed(1)} KB
              </span>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-4)', flexWrap: 'wrap' }}>
          {/* Live pipeline rail */}
          <div className="pipeline-rail" aria-label="Pipeline stage progression">
            {RAIL_STAGES.map((stg, idx) => {
              const result = stageMap[stg.key];
              const tone = railTone(result, idx === activeIdx);
              const prevDone = idx > 0 && Boolean(stageMap[RAIL_STAGES[idx - 1].key]);
              return (
                <React.Fragment key={stg.key}>
                  {idx > 0 && (
                    <span className={`rail-connector${prevDone ? ' rail-connector--done' : ''}`} />
                  )}
                  <span
                    className={`rail-node${tone ? ` rail-node--${tone}` : ''}`}
                    title={`${stg.short}: ${result?.status || (idx === activeIdx ? 'running' : 'pending')}`}
                  >
                    <span className="rail-dot">{stg.short}</span>
                  </span>
                </React.Fragment>
              );
            })}
          </div>

          {onReset && (
            <button onClick={onReset} className="btn">
              <Icon name="reset" size={13} />
              New Analysis
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
