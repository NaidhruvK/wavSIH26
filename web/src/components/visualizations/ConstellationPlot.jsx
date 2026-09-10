import React from 'react';
import PlotlyChart from './PlotlyChart';
import { parseConstellationData } from '../../utils/visualizerData';
import EmptyState from '../ui/EmptyState';
import MetricPill from '../ui/MetricPill';
import Icon from '../ui/icons';

export default function ConstellationPlot({ artifactData, imageUrl, stageValues }) {
  const parsed = parseConstellationData(artifactData);

  if (!parsed && !imageUrl) {
    return (
      <EmptyState icon="crosshair" title="Constellation Artifact Unavailable">
        Symbol constellation data has not been captured for this run or stage S3 has not completed.
      </EmptyState>
    );
  }

  if (!parsed && imageUrl) {
    return (
      <div className="inset" style={{ padding: 16, textAlign: 'center' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 12,
          }}
        >
          <span className="t-section" style={{ fontSize: 11 }}>
            S3 · Constellation Artifact
          </span>
          <a
            href={imageUrl}
            target="_blank"
            rel="noreferrer"
            className="badge badge--accent"
            style={{ textDecoration: 'none' }}
          >
            <Icon name="external" size={10} />
            Full Size
          </a>
        </div>
        <img
          src={imageUrl}
          alt="Constellation Diagram"
          style={{
            maxWidth: '100%',
            height: 'auto',
            maxHeight: 420,
            borderRadius: 'var(--radius-md)',
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
        color: '#4db8d8',
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
      line: { color: '#2b3850', width: 1 },
    },
    {
      type: 'line',
      x0: 0,
      x1: 0,
      y0: -parsed.bound,
      y1: parsed.bound,
      line: { color: '#2b3850', width: 1 },
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
      line: { color: '#3d4c66', width: 1, dash: 'dot' },
    },
  ];

  const layout = {
    title: {
      text: 'S3 · Complex Baseband Constellation (I/Q)',
      font: { color: '#e8edf4', size: 12, weight: 600 },
      x: 0.02,
    },
    xaxis: {
      title: { text: 'In-Phase (I)', font: { color: '#97a3b6', size: 11 } },
      range: [-parsed.bound, parsed.bound],
      zeroline: false,
    },
    yaxis: {
      title: { text: 'Quadrature (Q)', font: { color: '#97a3b6', size: 11 } },
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
      {/* Metric readouts */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
        {modulation && (
          <MetricPill label="Modulation" value={String(modulation).toUpperCase()} tone="accent" />
        )}
        {evm !== undefined && evm !== null && (
          <MetricPill
            label="EVM"
            value={`${Number(evm).toFixed(2)}%`}
            tone={Number(evm) < 15 ? 'ok' : 'warn'}
          />
        )}
        {lock && (
          <MetricPill
            label="Carrier Lock"
            value={typeof lock === 'number' ? (lock * 100).toFixed(1) + '%' : String(lock)}
            tone="ok"
          />
        )}
        <MetricPill
          label="Sampled"
          value={`${parsed.renderedCount} / ${parsed.originalCount}`}
          tone="muted"
          style={{ marginLeft: 'auto' }}
        />
      </div>

      <div style={{ maxWidth: 520, margin: '0 auto' }}>
        <PlotlyChart data={traces} layout={layout} style={{ minHeight: '380px' }} />
      </div>
    </div>
  );
}
