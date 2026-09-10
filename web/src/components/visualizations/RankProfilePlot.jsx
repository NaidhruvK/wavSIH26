import React from 'react';
import PlotlyChart from './PlotlyChart';
import { parseRankProfileData } from '../../utils/visualizerData';
import EmptyState from '../ui/EmptyState';
import MetricPill from '../ui/MetricPill';
import Icon from '../ui/icons';

export default function RankProfilePlot({ artifactData, imageUrl, stageValues }) {
  const parsed = parseRankProfileData(artifactData);

  if (!parsed && !imageUrl) {
    return (
      <EmptyState icon="barChart" title="Rank Profile Artifact Unavailable">
        GF(2) rank deficiency profile has not been generated for this run or stage S4 has not completed.
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
            S4 · Rank Profile Artifact
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
          alt="Rank Profile Chart"
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

  // Highlight peak period; keep other bars muted
  const colors = parsed.periods.map(p =>
    p === parsed.peakPeriod ? '#3ecf8e' : 'rgba(77, 184, 216, 0.6)'
  );

  const traces = [
    {
      x: parsed.periods,
      y: parsed.deficiencies,
      type: 'bar',
      name: 'GF(2) Rank Deficiency',
      marker: { color: colors },
      hovertemplate: 'Period L: %{x}<br>Rank Deficiency: %{y}<extra></extra>',
    },
  ];

  const annotations = [];
  if (parsed.peakPeriod && parsed.peakDeficiency > 0) {
    annotations.push({
      x: parsed.peakPeriod,
      y: parsed.peakDeficiency,
      xref: 'x',
      yref: 'y',
      text: `Peak Collapse (L=${parsed.peakPeriod}, def=${parsed.peakDeficiency})`,
      showarrow: true,
      arrowhead: 2,
      arrowsize: 1,
      arrowcolor: '#3ecf8e',
      font: { color: '#3ecf8e', size: 11 },
      bgcolor: 'rgba(9, 12, 18, 0.85)',
      bordercolor: '#3ecf8e',
      borderwidth: 1,
    });
  }

  const layout = {
    title: {
      text: 'S4 · GF(2) Matrix Rank Collapse Profile',
      font: { color: '#e8edf4', size: 12, weight: 600 },
      x: 0.02,
    },
    xaxis: {
      title: { text: 'Hypothesis Period L (Columns)', font: { color: '#97a3b6', size: 11 } },
    },
    yaxis: {
      title: { text: 'Rank Deficiency (L − rank)', font: { color: '#97a3b6', size: 11 } },
    },
    annotations,
  };

  const family = stageValues?.interleaver_family;
  const depth = stageValues?.interleaver_depth;
  const width = stageValues?.interleaver_width;
  const period = stageValues?.period || parsed.peakPeriod;

  return (
    <div>
      {/* Metric readouts */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
        {period && (
          <MetricPill label="Recovered Period L" value={period} tone="ok" />
        )}
        {family && (
          <MetricPill label="Interleaver Family" value={String(family)} tone="accent" />
        )}
        {depth && width && (
          <MetricPill label="Matrix Geometry" value={`${depth} × ${width}`} />
        )}
        <MetricPill
          label="Periods Swept"
          value={parsed.totalEvaluated}
          tone="muted"
          style={{ marginLeft: 'auto' }}
        />
      </div>

      <PlotlyChart data={traces} layout={layout} />
    </div>
  );
}
