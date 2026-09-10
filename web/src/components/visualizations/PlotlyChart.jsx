import React, { useEffect, useRef } from 'react';
import Plotly from 'plotly.js-dist-min';

const DEFAULT_THEME_LAYOUT = {
  paper_bgcolor: '#0b0f16',
  plot_bgcolor: '#090c12',
  font: {
    family: "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    size: 11,
    color: '#97a3b6',
  },
  margin: { l: 50, r: 24, t: 40, b: 45 },
  xaxis: {
    gridcolor: '#161d29',
    zerolinecolor: '#2b3850',
    tickfont: { color: '#5d6b80' },
  },
  yaxis: {
    gridcolor: '#161d29',
    zerolinecolor: '#2b3850',
    tickfont: { color: '#5d6b80' },
  },
  legend: {
    font: { color: '#97a3b6' },
    bgcolor: 'rgba(11, 15, 22, 0.85)',
    bordercolor: '#1c2433',
  },
  hoverlabel: {
    bgcolor: '#121722',
    bordercolor: '#4db8d8',
    font: { color: '#e8edf4', family: "'IBM Plex Mono', ui-monospace, monospace" },
  },
};

const DEFAULT_CONFIG = {
  responsive: true,
  displayModeBar: true,
  displaylogo: false,
  modeBarButtonsToRemove: ['lasso2d', 'select2d'],
};

export default function PlotlyChart({ data = [], layout = {}, config = {}, style = {} }) {
  const containerRef = useRef(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const mergedLayout = {
      ...DEFAULT_THEME_LAYOUT,
      ...layout,
      xaxis: {
        ...DEFAULT_THEME_LAYOUT.xaxis,
        ...(layout.xaxis || {}),
      },
      yaxis: {
        ...DEFAULT_THEME_LAYOUT.yaxis,
        ...(layout.yaxis || {}),
      },
      legend: {
        ...DEFAULT_THEME_LAYOUT.legend,
        ...(layout.legend || {}),
      },
      margin: {
        ...DEFAULT_THEME_LAYOUT.margin,
        ...(layout.margin || {}),
      },
    };

    const mergedConfig = {
      ...DEFAULT_CONFIG,
      ...config,
    };

    Plotly.react(el, data, mergedLayout, mergedConfig);

    const resizeObserver = new ResizeObserver(() => {
      Plotly.Plots.resize(el);
    });
    resizeObserver.observe(el);

    return () => {
      resizeObserver.disconnect();
      Plotly.purge(el);
    };
  }, [data, layout, config]);

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        minHeight: '340px',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
        ...style,
      }}
    />
  );
}
