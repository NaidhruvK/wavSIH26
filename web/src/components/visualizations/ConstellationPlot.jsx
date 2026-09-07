import React from 'react';
import PlotlyChart from './PlotlyChart';
import { parseConstellationData } from '../../utils/visualizerData';

export default function ConstellationPlot({ artifactData, imageUrl, stageValues }) {
  const parsed = parseConstellationData(artifactData);

  if (!parsed && !imageUrl) {
    return (
      <div style={{
        background: 'var(--bg-input)',
        padding: '36px 20px',
        textAlign: 'center',
        borderRadius: '8px',
        color: 'var(--text-dim)',
        fontSize: '13px',
      }}>
        <div style={{ fontSize: '24px', marginBottom: '8px' }}>🎯</div>
        <div style={{ fontWeight: 600, color: '#fff', marginBottom: '4px' }}>
          Constellation Artifact Unavailable
        </div>
        <div>
          Symbol constellation data has not been captured for this run or stage S3 has not completed.
        </div>
      </div>
    );
  }

  if (!parsed && imageUrl) {
    return (
      <div style={{
        background: 'var(--bg-input)',
        padding: '16px',
        borderRadius: '8px',
        textAlign: 'center',
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '12px',
        }}>
          <span style={{ fontSize: '12px', fontWeight: 700, color: '#fff' }}>
            S3 • Constellation Artifact
          </span>
          <a
            href={imageUrl}
            target="_blank"
            rel="noreferrer"
            style={{
              color: 'var(--cyan)',
              fontSize: '11px',
              textDecoration: 'none',
              background: 'rgba(6, 182, 212, 0.1)',
              padding: '3px 8px',
              borderRadius: '4px',
            }}
          >
            Open Full Size ↗
          </a>
        </div>
        <img
          src={imageUrl}
          alt="Constellation Diagram"
          style={{
            maxWidth: '100%',
            height: 'auto',
            maxHeight: '420px',
            borderRadius: '6px',
            border: '1px solid var(--border)',
          }}
        />
      </div>
    );
  }

  const traces = [
    {
      x: parsed.iPoints,
      y: parsed.qPoints,
      type: 'scatter',
      mode: 'markers',
      name: 'Symbols (I/Q)',
      marker: {
        color: '#06b6d4',
        size: 5,
        opacity: 0.65,
      },
      hovertemplate: 'I: %{x:.3f}<br>Q: %{y:.3f}<extra></extra>',
    },
  ];

  const shapes = [
    // Origin crosshairs
    {
      type: 'line',
      x0: -parsed.bound,
      x1: parsed.bound,
      y0: 0,
      y1: 0,
      line: { color: '#334155', width: 1 },
    },
    {
      type: 'line',
      x0: 0,
      x1: 0,
      y0: -parsed.bound,
      y1: parsed.bound,
      line: { color: '#334155', width: 1 },
    },
    // Normalized unit circle reference
    {
      type: 'circle',
      xref: 'x',
      yref: 'y',
      x0: -1.0,
      y0: -1.0,
      x1: 1.0,
      y1: 1.0,
      line: { color: '#475569', width: 1, dash: 'dot' },
    },
  ];

  const layout = {
    title: {
      text: 'S3 • Complex Baseband Constellation (I/Q)',
      font: { color: '#fff', size: 13, weight: 700 },
      x: 0.02,
    },
    xaxis: {
      title: { text: 'In-Phase (I)', font: { color: '#94a3b8', size: 11 } },
      range: [-parsed.bound, parsed.bound],
      zeroline: false,
    },
    yaxis: {
      title: { text: 'Quadrature (Q)', font: { color: '#94a3b8', size: 11 } },
      range: [-parsed.bound, parsed.bound],
      scaleanchor: 'x',
      scaleratio: 1,
      zeroline: false,
    },
    shapes,
  };

  const modulation = stageValues?.modulation;
  const evm = stageValues?.evm_percent;
  const lock = stageValues?.lock_status || stageValues?.carrier_lock;

  return (
    <div>
      {/* Metric badges */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '12px',
        marginBottom: '12px',
        fontSize: '11px',
      }}>
        {modulation && (
          <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
            <span style={{ color: 'var(--text-dim)' }}>Modulation: </span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan)', fontWeight: 700, textTransform: 'uppercase' }}>
              {modulation}
            </span>
          </div>
        )}
        {evm !== undefined && evm !== null && (
          <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
            <span style={{ color: 'var(--text-dim)' }}>EVM: </span>
            <span style={{ fontFamily: 'var(--font-mono)', color: Number(evm) < 15 ? 'var(--emerald)' : 'var(--amber)', fontWeight: 700 }}>
              {Number(evm).toFixed(2)}%
            </span>
          </div>
        )}
        {lock && (
          <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
            <span style={{ color: 'var(--text-dim)' }}>Carrier Lock: </span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--emerald)', fontWeight: 700 }}>
              {typeof lock === 'number' ? (lock * 100).toFixed(1) + '%' : String(lock)}
            </span>
          </div>
        )}
        <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px', marginLeft: 'auto' }}>
          <span style={{ color: 'var(--text-dim)' }}>Sampled Points: </span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
            {parsed.renderedCount} / {parsed.originalCount}
          </span>
        </div>
      </div>

      <div style={{ maxWidth: '520px', margin: '0 auto' }}>
        <PlotlyChart data={traces} layout={layout} style={{ minHeight: '380px' }} />
      </div>
    </div>
  );
}
