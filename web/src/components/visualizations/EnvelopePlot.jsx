import React, { useState } from 'react';
import PlotlyChart from './PlotlyChart';
import {
  EMPIRICAL_ENVELOPE_DATA,
  evaluateRunEnvelope,
  buildThresholdBarChartData,
  formatFrequency,
} from '../../utils/visualizerData';

const SCHEME_COLORS = {
  bpsk: '#06b6d4',
  qpsk: '#10b981',
  '2fsk': '#38bdf8',
  '4fsk': '#818cf8',
  '8psk': '#f59e0b',
  '16qam': '#a855f7',
};

export default function EnvelopePlot({ envelope, runReport }) {
  const [activeView, setActiveView] = useState('thresholds'); // 'thresholds' | 'empirical'

  const evaluation = evaluateRunEnvelope(envelope, runReport);
  const { bounds, run, checks, verdict, refusal } = evaluation;

  // Build S3 Zero-Error SNR Threshold Bar Chart
  const { traces: thresholdTraces, layout: thresholdLayout } = buildThresholdBarChartData(
    bounds.thresholds,
    run.snr,
    run.modulation
  );

  // Build Empirical EVM vs SNR Scatter Chart
  const empiricalTraces = Object.entries(EMPIRICAL_ENVELOPE_DATA).map(([scheme, points]) => ({
    x: points.map(p => p.snr),
    y: points.map(p => p.evm),
    type: 'scatter',
    mode: 'lines+markers',
    name: scheme.toUpperCase(),
    line: { color: SCHEME_COLORS[scheme] || '#94a3b8', width: 2 },
    marker: { size: 6 },
    hovertemplate: `<b>${scheme.toUpperCase()}</b><br>SNR: %{x} dB<br>EVM: %{y:.2f}%<extra></extra>`,
  }));

  const empiricalAnnotations = [];

  if (run.snr !== null && run.evm !== null) {
    empiricalTraces.push({
      x: [run.snr],
      y: [run.evm],
      type: 'scatter',
      mode: 'markers',
      name: 'Current Run',
      marker: {
        color: verdict === 'in_envelope' ? '#10b981' : verdict === 'failed' ? '#f43f5e' : '#f59e0b',
        size: 14,
        symbol: 'cross',
        line: { color: '#fff', width: 2 },
      },
      hovertemplate: `<b>Current Run (${run.modulation?.toUpperCase() || 'Captured'})</b><br>SNR: ${run.snr.toFixed(1)} dB<br>EVM: ${run.evm.toFixed(2)}%<br>Verdict: ${verdict}<extra></extra>`,
    });

    empiricalAnnotations.push({
      x: run.snr,
      y: run.evm,
      xref: 'x',
      yref: 'y',
      text: `Current Run (${run.snr.toFixed(1)} dB, ${run.evm.toFixed(1)}% EVM)`,
      showarrow: true,
      arrowhead: 2,
      arrowcolor: '#fff',
      font: { color: '#fff', size: 10, weight: 600 },
      bgcolor: 'rgba(15, 23, 42, 0.9)',
      bordercolor: '#06b6d4',
      borderwidth: 1,
    });
  }

  const empiricalLayout = {
    title: {
      text: 'Empirical EVM (%) vs Channel SNR (dB) Operating Curves',
      font: { color: '#fff', size: 13, weight: 700 },
      x: 0.02,
    },
    xaxis: {
      title: { text: 'Channel SNR (dB)', font: { color: '#94a3b8', size: 11 } },
      dtick: 2,
    },
    yaxis: {
      title: { text: 'Error Vector Magnitude EVM (%)', font: { color: '#94a3b8', size: 11 } },
    },
    annotations: empiricalAnnotations,
  };

  const getVerdictBadge = () => {
    switch (verdict.toLowerCase()) {
      case 'in_envelope':
        return { color: 'var(--emerald)', bg: 'rgba(16, 185, 129, 0.1)', border: 'rgba(16, 185, 129, 0.4)', text: 'IN ENVELOPE' };
      case 'out_of_envelope':
        return { color: 'var(--amber)', bg: 'rgba(245, 158, 11, 0.1)', border: 'rgba(245, 158, 11, 0.4)', text: 'OUT OF ENVELOPE (REFUSED)' };
      case 'low_confidence':
        return { color: 'var(--amber)', bg: 'rgba(245, 158, 11, 0.1)', border: 'rgba(245, 158, 11, 0.4)', text: 'LOW CONFIDENCE' };
      case 'failed':
        return { color: 'var(--rose)', bg: 'rgba(244, 63, 94, 0.1)', border: 'rgba(244, 63, 94, 0.4)', text: 'FAILED' };
      default:
        return { color: 'var(--text-dim)', bg: 'rgba(100, 116, 139, 0.1)', border: 'rgba(100, 116, 139, 0.3)', text: 'PENDING / NO RUN' };
    }
  };

  const badge = getVerdictBadge();

  const renderStatusTag = (isInBounds) => {
    if (isInBounds === true) {
      return (
        <span style={{
          fontSize: '9px',
          fontWeight: 700,
          color: 'var(--emerald)',
          background: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.4)',
          borderRadius: '3px',
          padding: '2px 5px',
        }}>
          PASS
        </span>
      );
    }
    if (isInBounds === false) {
      return (
        <span style={{
          fontSize: '9px',
          fontWeight: 700,
          color: 'var(--amber)',
          background: 'rgba(245, 158, 11, 0.15)',
          border: '1px solid rgba(245, 158, 11, 0.4)',
          borderRadius: '3px',
          padding: '2px 5px',
        }}>
          REFUSED
        </span>
      );
    }
    return (
      <span style={{
        fontSize: '9px',
        fontWeight: 600,
        color: 'var(--text-dim)',
        background: 'rgba(100, 116, 139, 0.15)',
        border: '1px solid rgba(100, 116, 139, 0.3)',
        borderRadius: '3px',
        padding: '2px 5px',
      }}>
        SPEC
      </span>
    );
  };

  return (
    <div>
      {/* Top Envelope Header & Verdict Badge */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        marginBottom: '12px',
        padding: '10px 14px',
        background: 'var(--bg-input)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
      }}>
        <div>
          <div style={{ fontSize: '11px', fontWeight: 800, color: '#fff', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            RF Operating Envelope Engine
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text-dim)', marginTop: '2px' }}>
            Enforces physical signal acquisition ranges & demodulation SNR gates.
          </div>
        </div>
        <div>
          <span style={{
            fontSize: '11px',
            fontWeight: 800,
            fontFamily: 'var(--font-mono)',
            padding: '5px 10px',
            borderRadius: '4px',
            color: badge.color,
            background: badge.bg,
            border: `1px solid ${badge.border}`,
            display: 'inline-block',
          }}>
            {badge.text}
          </span>
        </div>
      </div>

      {/* Refusal / In-Spec Alert Banner */}
      {refusal && (
        <div style={{
          marginBottom: '12px',
          padding: '10px 14px',
          borderRadius: '6px',
          background: 'rgba(245, 158, 11, 0.1)',
          border: '1px solid rgba(245, 158, 11, 0.35)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          fontSize: '12px',
          color: 'var(--amber)',
        }}>
          <span style={{ fontSize: '14px' }}>⚠️</span>
          <div>
            <span style={{ fontWeight: 800, textTransform: 'uppercase', marginRight: '6px' }}>
              Operating Envelope Refusal [{refusal.stage}]:
            </span>
            <span>{refusal.reason}</span>
          </div>
        </div>
      )}

      {!refusal && verdict === 'in_envelope' && (
        <div style={{
          marginBottom: '12px',
          padding: '10px 14px',
          borderRadius: '6px',
          background: 'rgba(16, 185, 129, 0.08)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          fontSize: '12px',
          color: 'var(--emerald)',
        }}>
          <span style={{ fontSize: '14px' }}>✓</span>
          <div>
            <span style={{ fontWeight: 800, marginRight: '6px' }}>SIGNAL WITHIN OPERATING ENVELOPE:</span>
            <span>All signal parameters (Fs, SNR, OBW, SPS, CFO) satisfy declared pipeline requirements.</span>
          </div>
        </div>
      )}

      {/* 4-Stage Operating Envelope Cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: '10px',
        marginBottom: '14px',
      }}>
        {/* S0 Ingest Card */}
        <div style={{
          background: 'var(--bg-input)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          padding: '10px 12px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
            <span style={{ fontSize: '10px', fontWeight: 800, color: 'var(--cyan)' }}>S0 INGEST</span>
            {renderStatusTag(checks.s0InBounds)}
          </div>
          <div style={{ fontSize: '9px', color: 'var(--text-dim)', marginBottom: '4px' }}>
            Declared: 8 kHz – 20 MHz
          </div>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#fff', fontFamily: 'var(--font-mono)' }}>
            {run.fs !== null ? formatFrequency(run.fs) : '—'}
          </div>
        </div>

        {/* S1 Detect Card */}
        <div style={{
          background: 'var(--bg-input)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          padding: '10px 12px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
            <span style={{ fontSize: '10px', fontWeight: 800, color: 'var(--cyan)' }}>S1 DETECT</span>
            {renderStatusTag(checks.s1InBounds)}
          </div>
          <div style={{ fontSize: '9px', color: 'var(--text-dim)', marginBottom: '4px' }}>
            Min SNR: ≥ -5.0 dB | OBW: ≥ 1 kHz
          </div>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#fff', fontFamily: 'var(--font-mono)' }}>
            {run.snr !== null ? `${run.snr.toFixed(1)} dB` : '—'}
            <span style={{ fontSize: '10px', color: 'var(--text-dim)', marginLeft: '6px' }}>
              {run.obw !== null ? formatFrequency(run.obw) : ''}
            </span>
          </div>
        </div>

        {/* S2 Estimate Card */}
        <div style={{
          background: 'var(--bg-input)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          padding: '10px 12px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
            <span style={{ fontSize: '10px', fontWeight: 800, color: 'var(--cyan)' }}>S2 ESTIMATE</span>
            {renderStatusTag(checks.s2InBounds)}
          </div>
          <div style={{ fontSize: '9px', color: 'var(--text-dim)', marginBottom: '4px' }}>
            SPS: 2.5–40.0 | CFO: ±50 kHz
          </div>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#fff', fontFamily: 'var(--font-mono)' }}>
            {run.sps !== null ? `${run.sps.toFixed(2)} SPS` : '—'}
            <span style={{ fontSize: '10px', color: 'var(--text-dim)', marginLeft: '6px' }}>
              {run.cfo !== null ? formatFrequency(run.cfo) : ''}
            </span>
          </div>
        </div>

        {/* S3 Receive Card */}
        <div style={{
          background: 'var(--bg-input)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          padding: '10px 12px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
            <span style={{ fontSize: '10px', fontWeight: 800, color: 'var(--cyan)' }}>S3 RECEIVE</span>
            {renderStatusTag(checks.s3InBounds)}
          </div>
          <div style={{ fontSize: '9px', color: 'var(--text-dim)', marginBottom: '4px' }}>
            Zero-Error Gate: 8–20 dB
          </div>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#fff', fontFamily: 'var(--font-mono)' }}>
            {run.modulation ? run.modulation.toUpperCase() : 'MOD: —'}
            <span style={{ fontSize: '10px', color: 'var(--text-dim)', marginLeft: '6px' }}>
              {run.modThreshold !== null ? `(Req: ${run.modThreshold} dB)` : ''}
            </span>
          </div>
        </div>
      </div>

      {/* Chart View Switcher */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: '10px',
      }}>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={() => setActiveView('thresholds')}
            style={{
              padding: '6px 12px',
              fontSize: '11px',
              fontWeight: 700,
              fontFamily: 'var(--font-mono)',
              borderRadius: '4px',
              cursor: 'pointer',
              background: activeView === 'thresholds' ? 'rgba(6, 182, 212, 0.15)' : 'var(--bg-input)',
              color: activeView === 'thresholds' ? 'var(--cyan)' : 'var(--text-dim)',
              border: activeView === 'thresholds' ? '1px solid var(--cyan)' : '1px solid var(--border)',
            }}
          >
            📊 S3 Zero-Error SNR Gates
          </button>
          <button
            onClick={() => setActiveView('empirical')}
            style={{
              padding: '6px 12px',
              fontSize: '11px',
              fontWeight: 700,
              fontFamily: 'var(--font-mono)',
              borderRadius: '4px',
              cursor: 'pointer',
              background: activeView === 'empirical' ? 'rgba(6, 182, 212, 0.15)' : 'var(--bg-input)',
              color: activeView === 'empirical' ? 'var(--cyan)' : 'var(--text-dim)',
              border: activeView === 'empirical' ? '1px solid var(--cyan)' : '1px solid var(--border)',
            }}
          >
            📈 Empirical EVM vs SNR Curves
          </button>
        </div>
        <div style={{ fontSize: '10px', color: 'var(--text-dim)' }}>
          {activeView === 'thresholds' ? 'Interactive modulation gates' : 'Multi-scheme demodulation curves'}
        </div>
      </div>

      {/* Active Chart Component */}
      {activeView === 'thresholds' ? (
        <PlotlyChart data={thresholdTraces} layout={thresholdLayout} />
      ) : (
        <PlotlyChart data={empiricalTraces} layout={empiricalLayout} />
      )}
    </div>
  );
}
