import React, { useState } from 'react';
import PlotlyChart from './PlotlyChart';
import {
  EMPIRICAL_ENVELOPE_DATA,
  evaluateRunEnvelope,
  buildThresholdBarChartData,
  formatFrequency,
} from '../../utils/visualizerData';
import StatusBadge from '../ui/StatusBadge';
import Icon from '../ui/icons';

const SCHEME_COLORS = {
  bpsk: '#4db8d8',
  qpsk: '#3ecf8e',
  '2fsk': '#6fd0ec',
  '4fsk': '#8b9cf5',
  '8psk': '#e0a83e',
  '16qam': '#b083e8',
};

function CheckTag({ isInBounds }) {
  if (isInBounds === true) {
    return <span className="badge badge--ok" style={{ fontSize: 9, padding: '1px 6px' }}>PASS</span>;
  }
  if (isInBounds === false) {
    return <span className="badge badge--warn" style={{ fontSize: 9, padding: '1px 6px' }}>REFUSED</span>;
  }
  return <span className="badge badge--neutral" style={{ fontSize: 9, padding: '1px 6px' }}>SPEC</span>;
}

function EnvelopeCheckCard({ stage, tag, spec, children }) {
  return (
    <div className="inset" style={{ padding: '10px 12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
        <span className="t-label" style={{ color: 'var(--accent)', fontSize: 9 }}>{stage}</span>
        {tag}
      </div>
      <div className="t-caption" style={{ fontSize: 10, marginBottom: 4 }}>{spec}</div>
      <div className="t-data" style={{ fontSize: 12, fontWeight: 600 }}>{children}</div>
    </div>
  );
}

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

  // Build Empirical EVM vs SNR Scatter Chart.
  //
  // Only schemes that actually HAVE an EVM measurement are drawn. EVM is a
  // distance to a fixed constellation point, and the FSK receiver is a
  // non-coherent frequency discriminator with no constellation, so
  // reports/s3_envelope.csv leaves evm_percent empty on every FSK row and
  // EMPIRICAL_ENVELOPE_DATA carries null. Plotting a curve there means
  // inventing it, which is exactly what this block used to do.
  const evmSchemes = Object.entries(EMPIRICAL_ENVELOPE_DATA)
    .map(([scheme, points]) => [scheme, points.filter(p => typeof p.evm === 'number')])
    .filter(([, points]) => points.length > 0);

  const noEvmSchemes = Object.entries(EMPIRICAL_ENVELOPE_DATA)
    .filter(([, points]) => !points.some(p => typeof p.evm === 'number'))
    .map(([scheme]) => scheme.toUpperCase());

  const empiricalTraces = evmSchemes.map(([scheme, points]) => ({
    x: points.map(p => p.snr),
    y: points.map(p => p.evm),
    type: 'scatter',
    mode: 'lines+markers',
    name: scheme.toUpperCase(),
    line: { color: SCHEME_COLORS[scheme] || '#97a3b6', width: 2 },
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
        color: verdict === 'in_envelope' ? '#3ecf8e' : verdict === 'failed' ? '#e0564d' : '#e0a83e',
        size: 14,
        symbol: 'cross',
        line: { color: '#e8edf4', width: 2 },
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
      arrowcolor: '#e8edf4',
      font: { color: '#e8edf4', size: 10 },
      bgcolor: 'rgba(9, 12, 18, 0.9)',
      bordercolor: '#4db8d8',
      borderwidth: 1,
    });
  }

  const empiricalLayout = {
    title: {
      text: 'Empirical EVM (%) vs Channel SNR (dB) Operating Curves',
      font: { color: '#e8edf4', size: 12, weight: 600 },
      x: 0.02,
    },
    xaxis: {
      title: { text: 'Channel SNR (dB)', font: { color: '#97a3b6', size: 11 } },
      dtick: 2,
    },
    yaxis: {
      title: { text: 'Error Vector Magnitude EVM (%)', font: { color: '#97a3b6', size: 11 } },
    },
    annotations: empiricalAnnotations,
  };

  return (
    <div>
      {/* Envelope header & verdict */}
      <div
        className="inset"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          marginBottom: 12,
          padding: '10px 14px',
        }}
      >
        <div>
          <div className="t-section" style={{ fontSize: 11 }}>
            RF Operating Envelope Engine
          </div>
          <div className="t-caption" style={{ fontSize: 10, marginTop: 2 }}>
            Enforces physical signal acquisition ranges & demodulation SNR gates.
          </div>
        </div>
        <StatusBadge
          status={verdict}
          label={verdict === 'out_of_envelope' ? 'OUT OF ENVELOPE (REFUSED)' : verdict === 'pending' ? 'PENDING / NO RUN' : undefined}
        />
      </div>

      {/* Refusal / In-Spec Alert Banner */}
      {refusal && (
        <div
          role="alert"
          style={{
            marginBottom: 12,
            padding: '10px 14px',
            borderRadius: 'var(--radius-md)',
            background: 'var(--warn-dim)',
            border: '1px solid var(--warn-border)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            fontSize: 12,
            color: 'var(--warn)',
          }}
        >
          <Icon name="alert" size={15} />
          <div>
            <span style={{ fontWeight: 700, textTransform: 'uppercase', marginRight: 6, letterSpacing: '0.04em' }}>
              Operating Envelope Refusal [{refusal.stage}]:
            </span>
            <span>{refusal.reason}</span>
          </div>
        </div>
      )}

      {!refusal && verdict === 'in_envelope' && (
        <div
          style={{
            marginBottom: 12,
            padding: '10px 14px',
            borderRadius: 'var(--radius-md)',
            background: 'var(--ok-dim)',
            border: '1px solid var(--ok-border)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            fontSize: 12,
            color: 'var(--ok)',
          }}
        >
          <Icon name="check" size={15} />
          <div>
            <span style={{ fontWeight: 700, marginRight: 6, letterSpacing: '0.04em' }}>SIGNAL WITHIN OPERATING ENVELOPE:</span>
            <span>All signal parameters (Fs, SNR, OBW, SPS, CFO) satisfy declared pipeline requirements.</span>
          </div>
        </div>
      )}

      {/* 4-Stage Operating Envelope Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: 10,
          marginBottom: 14,
        }}
      >
        <EnvelopeCheckCard stage="S0 Ingest" tag={<CheckTag isInBounds={checks.s0InBounds} />} spec="Declared: 8 kHz – 20 MHz">
          {run.fs !== null ? formatFrequency(run.fs) : '—'}
        </EnvelopeCheckCard>

        <EnvelopeCheckCard stage="S1 Detect" tag={<CheckTag isInBounds={checks.s1InBounds} />} spec="Min SNR: ≥ −5.0 dB | OBW: ≥ 1 kHz">
          {run.snr !== null ? `${run.snr.toFixed(1)} dB` : '—'}
          <span style={{ fontSize: 10, color: 'var(--text-tertiary)', marginLeft: 6 }}>
            {run.obw !== null ? formatFrequency(run.obw) : ''}
          </span>
        </EnvelopeCheckCard>

        <EnvelopeCheckCard stage="S2 Estimate" tag={<CheckTag isInBounds={checks.s2InBounds} />} spec="SPS: 2.5–40.0 | CFO: ±50 kHz">
          {run.sps !== null ? `${run.sps.toFixed(2)} SPS` : '—'}
          <span style={{ fontSize: 10, color: 'var(--text-tertiary)', marginLeft: 6 }}>
            {run.cfo !== null ? formatFrequency(run.cfo) : ''}
          </span>
        </EnvelopeCheckCard>

        <EnvelopeCheckCard stage="S3 Receive" tag={<CheckTag isInBounds={checks.s3InBounds} />} spec="Zero-Error Gate: 8–20 dB">
          {run.modulation ? run.modulation.toUpperCase() : 'MOD: —'}
          <span style={{ fontSize: 10, color: 'var(--text-tertiary)', marginLeft: 6 }}>
            {run.modThreshold !== null ? `(Req: ${run.modThreshold} dB)` : ''}
          </span>
        </EnvelopeCheckCard>
      </div>

      {/* Chart View Switcher */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 10,
          flexWrap: 'wrap',
          marginBottom: 10,
        }}
      >
        <div role="tablist" aria-label="Envelope chart view" style={{ display: 'flex', gap: 6 }}>
          <button
            role="tab"
            aria-selected={activeView === 'thresholds'}
            onClick={() => setActiveView('thresholds')}
            className={`tab-btn${activeView === 'thresholds' ? ' is-active' : ''}`}
          >
            <Icon name="barChart" size={12} />
            S3 Zero-Error SNR Gates
          </button>
          <button
            role="tab"
            aria-selected={activeView === 'empirical'}
            onClick={() => setActiveView('empirical')}
            className={`tab-btn${activeView === 'empirical' ? ' is-active' : ''}`}
          >
            <Icon name="trend" size={12} />
            Empirical EVM vs SNR
          </button>
        </div>
        <div className="t-caption" style={{ fontSize: 10 }}>
          {activeView === 'thresholds' ? 'Interactive modulation gates' : 'Multi-scheme demodulation curves'}
        </div>
      </div>

      {/* Active Chart Component */}
      {activeView === 'thresholds' ? (
        <>
          <PlotlyChart data={thresholdTraces} layout={thresholdLayout} />
          <div className="t-caption" style={{ fontSize: 10, marginTop: 6, lineHeight: 1.5 }}>
            Lowest swept SNR with <strong>measured_ber == 0</strong> in
            reports/s3_envelope.csv. A bar marked <strong>&le;</strong> is an upper
            bound, not a measured crossing: the lowest SNR tested was already
            error-free, so the true threshold lies at or below it. Only 8PSK and
            16QAM have a crossing inside the swept range.
          </div>
        </>
      ) : (
        <>
          <PlotlyChart data={empiricalTraces} layout={empiricalLayout} />
          {noEvmSchemes.length > 0 && (
            <div className="t-caption" style={{ fontSize: 10, marginTop: 6, lineHeight: 1.5 }}>
              {noEvmSchemes.join(' and ')} are not plotted: EVM is a distance to a
              fixed constellation point and the FSK receiver is a non-coherent
              frequency discriminator, so no EVM is measured for them. Their
              carrier-lock figures are in reports/s3_envelope.csv.
            </div>
          )}
        </>
      )}
    </div>
  );
}
