import React from 'react';
import PlotlyChart from './PlotlyChart';
import { parseRankProfileData } from '../../utils/visualizerData';

export default function RankProfilePlot({ artifactData, imageUrl, stageValues }) {
  const parsed = parseRankProfileData(artifactData);

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
        <div style={{ fontSize: '24px', marginBottom: '8px' }}>📉</div>
        <div style={{ fontWeight: 600, color: '#fff', marginBottom: '4px' }}>
          Rank Profile Artifact Unavailable
        </div>
        <div>
          GF(2) rank deficiency profile has not been generated for this run or stage S4 has not completed.
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
            S4 • Rank Profile Artifact
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
          alt="Rank Profile Chart"
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

  // Highlight peak period with emerald, others with muted cyan
  const colors = parsed.periods.map(p =>
    p === parsed.peakPeriod ? '#10b981' : 'rgba(56, 189, 248, 0.75)'
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
      arrowcolor: '#10b981',
      font: { color: '#10b981', size: 11, weight: 600 },
      bgcolor: 'rgba(15, 23, 42, 0.85)',
      bordercolor: '#10b981',
      borderwidth: 1,
    });
  }

  const layout = {
    title: {
      text: 'S4 • GF(2) Matrix Rank Collapse Profile',
      font: { color: '#fff', size: 13, weight: 700 },
      x: 0.02,
    },
    xaxis: {
      title: { text: 'Hypothesis Period L (Columns)', font: { color: '#94a3b8', size: 11 } },
    },
    yaxis: {
      title: { text: 'Rank Deficiency (L - rank)', font: { color: '#94a3b8', size: 11 } },
    },
    annotations,
  };

  const family = stageValues?.interleaver_family;
  const depth = stageValues?.interleaver_depth;
  const width = stageValues?.interleaver_width;
  const period = stageValues?.period || parsed.peakPeriod;

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
        {period && (
          <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
            <span style={{ color: 'var(--text-dim)' }}>Recovered Period L: </span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--emerald)', fontWeight: 700 }}>
              {period}
            </span>
          </div>
        )}
        {family && (
          <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
            <span style={{ color: 'var(--text-dim)' }}>Interleaver Family: </span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan)', fontWeight: 700, textTransform: 'capitalize' }}>
              {family}
            </span>
          </div>
        )}
        {depth && width && (
          <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
            <span style={{ color: 'var(--text-dim)' }}>Matrix Geometry: </span>
            <span style={{ fontFamily: 'var(--font-mono)', color: '#fff', fontWeight: 700 }}>
              {depth} × {width}
            </span>
          </div>
        )}
        <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px', marginLeft: 'auto' }}>
          <span style={{ color: 'var(--text-dim)' }}>Periods Swept: </span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
            {parsed.totalEvaluated}
          </span>
        </div>
      </div>

      <PlotlyChart data={traces} layout={layout} />
    </div>
  );
}
