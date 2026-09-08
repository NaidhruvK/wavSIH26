import React from 'react';
import PlotlyChart from './PlotlyChart';
import { EMPIRICAL_ENVELOPE_DATA } from '../../utils/visualizerData';

const SCHEME_COLORS = {
  bpsk: '#06b6d4',
  qpsk: '#10b981',
  '8psk': '#f59e0b',
  '16qam': '#a855f7',
};

export default function EnvelopePlot({ envelope, runReport }) {
  // Extract current run operating point
  let currentSnr = null;
  let currentEvm = null;
  let currentMod = null;
  let verdict = runReport?.envelope_verdict || 'pending';

  if (runReport?.stages) {
    const s1 = runReport.stages.find(s => s.stage === 's1_detect');
    const s3 = runReport.stages.find(s => s.stage === 's3_receive');
    if (s1?.values?.snr_db !== undefined && s1?.values?.snr_db !== null) {
      currentSnr = Number(s1.values.snr_db);
    }
    if (s3?.values?.evm_percent !== undefined && s3?.values?.evm_percent !== null) {
      currentEvm = Number(s3.values.evm_percent);
    }
    if (s3?.values?.modulation) {
      currentMod = String(s3.values.modulation).toLowerCase();
    }
  }

  // Generate traces for each modulation scheme
  const traces = Object.entries(EMPIRICAL_ENVELOPE_DATA).map(([scheme, points]) => ({
    x: points.map(p => p.snr),
    y: points.map(p => p.evm),
    type: 'scatter',
    mode: 'lines+markers',
    name: scheme.toUpperCase(),
    line: { color: SCHEME_COLORS[scheme] || '#94a3b8', width: 2 },
    marker: { size: 6 },
    hovertemplate: `<b>${scheme.toUpperCase()}</b><br>SNR: %{x} dB<br>EVM: %{y:.2f}%<extra></extra>`,
  }));

  const annotations = [];

  // If current run has measured operating coordinates, overlay target marker
  if (currentSnr !== null && currentEvm !== null) {
    traces.push({
      x: [currentSnr],
      y: [currentEvm],
      type: 'scatter',
      mode: 'markers',
      name: 'Current Run',
      marker: {
        color: verdict === 'in_envelope' ? '#10b981' : verdict === 'failed' ? '#f43f5e' : '#f59e0b',
        size: 14,
        symbol: 'cross',
        line: { color: '#fff', width: 2 },
      },
      hovertemplate: `<b>Current Run (${currentMod?.toUpperCase() || 'Captured'})</b><br>SNR: ${currentSnr.toFixed(1)} dB<br>EVM: ${currentEvm.toFixed(2)}%<br>Verdict: ${verdict}<extra></extra>`,
    });

    annotations.push({
      x: currentSnr,
      y: currentEvm,
      xref: 'x',
      yref: 'y',
      text: `Current Run (${currentSnr.toFixed(1)} dB, ${currentEvm.toFixed(1)}% EVM)`,
      showarrow: true,
      arrowhead: 2,
      arrowcolor: '#fff',
      font: { color: '#fff', size: 10, weight: 600 },
      bgcolor: 'rgba(15, 23, 42, 0.9)',
      bordercolor: '#06b6d4',
      borderwidth: 1,
    });
  }

  const layout = {
    title: {
      text: 'Operating Envelope • Receiver EVM (%) vs Channel SNR (dB)',
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
    annotations,
  };

  const getVerdictBadge = () => {
    switch (verdict.toLowerCase()) {
      case 'in_envelope':
        return { color: 'var(--emerald)', bg: 'rgba(16, 185, 129, 0.1)', text: 'IN ENVELOPE' };
      case 'out_of_envelope':
        return { color: 'var(--amber)', bg: 'rgba(245, 158, 11, 0.1)', text: 'OUT OF ENVELOPE' };
      case 'low_confidence':
        return { color: 'var(--amber)', bg: 'rgba(245, 158, 11, 0.1)', text: 'LOW CONFIDENCE' };
      case 'failed':
        return { color: 'var(--rose)', bg: 'rgba(244, 63, 94, 0.1)', text: 'FAILED' };
      default:
        return { color: 'var(--text-dim)', bg: 'rgba(100, 116, 139, 0.1)', text: 'NO ACTIVE RUN' };
    }
  };

  const badge = getVerdictBadge();

  return (
    <div>
      {/* Metric badges */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: '12px',
        marginBottom: '12px',
        fontSize: '11px',
      }}>
        <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
          <span style={{ color: 'var(--text-dim)' }}>Declared Min SNR: </span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan)', fontWeight: 700 }}>
            {envelope?.stages?.s1_detect?.min_snr_db ?? -5.0} dB
          </span>
        </div>
        <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
          <span style={{ color: 'var(--text-dim)' }}>Zero-Error SNR Gate: </span>
          <span style={{ fontFamily: 'var(--font-mono)', color: '#fff', fontWeight: 700 }}>
            {envelope?.stages?.s3_receive?.zero_error_snr_threshold_db ?? 8.0} dB
          </span>
        </div>
        {currentSnr !== null && (
          <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
            <span style={{ color: 'var(--text-dim)' }}>Run Operating Point: </span>
            <span style={{ fontFamily: 'var(--font-mono)', color: '#fff', fontWeight: 700 }}>
              {currentSnr.toFixed(1)} dB @ {currentEvm !== null ? `${currentEvm.toFixed(1)}% EVM` : '—'}
            </span>
          </div>
        )}
        <div style={{ marginLeft: 'auto' }}>
          <span style={{
            fontSize: '10px',
            fontWeight: 700,
            fontFamily: 'var(--font-mono)',
            padding: '4px 8px',
            borderRadius: '4px',
            color: badge.color,
            background: badge.bg,
            border: `1px solid ${badge.color}44`,
          }}>
            {badge.text}
          </span>
        </div>
      </div>

      <PlotlyChart data={traces} layout={layout} />
    </div>
  );
}
