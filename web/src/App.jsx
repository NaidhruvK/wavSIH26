import React, { useState, useEffect, useRef } from 'react';
import Header from './components/Header';
import UploadZone from './components/UploadZone';
import RunStatusBanner from './components/RunStatusBanner';
import StageCard from './components/StageCard';
import PayloadViewer from './components/PayloadViewer';
import EnvelopeModal from './components/EnvelopeModal';
import RegistryDrawer from './components/RegistryDrawer';
import VisualizationCenter from './components/visualizations/VisualizationCenter';
import Icon from './components/ui/icons';
import {
  uploadAndAnalyze,
  getRunReport,
  getHealth,
  getRegistry,
  getEnvelope,
} from './api';

const STAGE_KEYS = [
  's0_ingest',
  's1_detect',
  's2_estimate',
  's3_receive',
  's4_recover',
  's5_decode',
  's6_frame',
];

export default function App() {
  const [health, setHealth] = useState(null);
  const [registry, setRegistry] = useState(null);
  const [envelope, setEnvelope] = useState(null);

  const [runId, setRunId] = useState(null);
  const [report, setReport] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [appError, setAppError] = useState(null);

  const [showEnvelopeModal, setShowEnvelopeModal] = useState(false);
  const [showRegistryDrawer, setShowRegistryDrawer] = useState(false);

  const pollIntervalRef = useRef(null);

  // Initial metadata fetch
  useEffect(() => {
    async function loadMeta() {
      try {
        const h = await getHealth();
        setHealth(h);
      } catch (err) {
        setHealth({ status: 'offline', error: err.message });
      }

      try {
        const r = await getRegistry();
        setRegistry(r);
      } catch (err) {
        // Optional
      }

      try {
        const env = await getEnvelope();
        setEnvelope(env);
      } catch (err) {
        // Optional
      }
    }
    loadMeta();
  }, []);

  // Polling manager
  useEffect(() => {
    if (!runId || !isPolling) return;

    let attempts = 0;
    const maxAttempts = 60; // 60 * 1.5s = 90s (matches config.total_timeout_seconds)

    async function poll() {
      attempts += 1;
      try {
        const currentReport = await getRunReport(runId);
        setReport(currentReport);

        const st = currentReport.status?.toLowerCase();
        if (st === 'completed' || st === 'failed' || attempts >= maxAttempts) {
          setIsPolling(false);
          clearInterval(pollIntervalRef.current);
        }
      } catch (err) {
        // Keep retrying while job starts
        if (attempts >= maxAttempts) {
          setIsPolling(false);
          clearInterval(pollIntervalRef.current);
          setAppError(`Polling stopped: ${err.message}`);
        }
      }
    }

    // Initial immediate check then recurring
    poll();
    pollIntervalRef.current = setInterval(poll, 1500);

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [runId, isPolling]);

  const handleStartAnalysis = async (file, fsHint, modHint) => {
    setIsAnalyzing(true);
    setAppError(null);
    setReport(null);

    try {
      const initResp = await uploadAndAnalyze(file, fsHint, modHint);
      setRunId(initResp.run_id);
      setIsPolling(true);
    } catch (err) {
      setAppError(err.message || 'Failed to submit analysis job.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleReset = () => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    setRunId(null);
    setReport(null);
    setIsPolling(false);
    setAppError(null);
  };

  // Map stages from report
  const stageResultsMap = {};
  if (report?.stages) {
    report.stages.forEach(stg => {
      stageResultsMap[stg.stage] = stg;
    });
  }

  const s6Stage = stageResultsMap['s6_frame'];

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Header
        health={health}
        onOpenEnvelope={() => setShowEnvelopeModal(true)}
        onOpenRegistry={() => setShowRegistryDrawer(true)}
      />

      <main className="app-main">
        {appError && (
          <div
            role="alert"
            style={{
              background: 'var(--danger-dim)',
              color: 'var(--danger)',
              border: '1px solid var(--danger-border)',
              padding: '10px 14px',
              borderRadius: 'var(--radius-md)',
              marginBottom: 'var(--sp-5)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 12,
              fontSize: 13,
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Icon name="alert" size={15} />
              {appError}
            </span>
            <button
              onClick={() => setAppError(null)}
              aria-label="Dismiss error"
              className="btn btn--ghost btn--icon"
              style={{ color: 'var(--danger)' }}
            >
              <Icon name="x" size={13} />
            </button>
          </div>
        )}

        {/* Upload Component */}
        <UploadZone onAnalyze={handleStartAnalysis} isAnalyzing={isAnalyzing} />

        {/* Active Run Status Banner */}
        <RunStatusBanner
          runId={runId}
          report={report}
          isPolling={isPolling}
          onReset={handleReset}
        />

        {/* S0 to S6 Stage Progression Grid */}
        <section style={{ marginBottom: 'var(--sp-5)' }} aria-label="Pipeline execution stages">
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'baseline',
              gap: 12,
              flexWrap: 'wrap',
              marginBottom: 12,
            }}
          >
            <h2 className="t-section">Pipeline Execution · S0 → S6</h2>
            <span className="t-label">Sequential Demodulation & Coding Resolution</span>
          </div>

          <div className="stage-grid">
            {STAGE_KEYS.map(stgKey => (
              <StageCard
                key={stgKey}
                stageName={stgKey}
                stageResult={stageResultsMap[stgKey]}
                runId={runId}
              />
            ))}
          </div>
        </section>

        {/* RF Telemetry & Advanced Signal Visualization Center */}
        <VisualizationCenter
          runId={runId}
          report={report}
          envelope={envelope}
        />

        {/* Telemetry Payload Viewer (S6) */}
        <PayloadViewer
          finalPayload={report?.final}
          s6Stage={s6Stage}
        />
      </main>

      {/* Operating Envelope Modal */}
      {showEnvelopeModal && (
        <EnvelopeModal
          envelope={envelope}
          onClose={() => setShowEnvelopeModal(false)}
        />
      )}

      {/* Registry Drawer */}
      {showRegistryDrawer && (
        <RegistryDrawer
          registry={registry}
          onClose={() => setShowRegistryDrawer(false)}
        />
      )}

      <footer
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
          padding: '14px 20px',
          borderTop: '1px solid var(--border)',
        }}
      >
        <span className="t-label" style={{ fontSize: 9 }}>
          Raaya (wavSIH26) · Team Raaya
        </span>
        <span className="t-label" style={{ fontSize: 9 }}>
          Blind RF Signal Intelligence System
        </span>
      </footer>
    </div>
  );
}
