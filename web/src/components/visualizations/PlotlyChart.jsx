import React, { useEffect, useRef } from 'react';
import Plotly from 'plotly.js-dist-min';

const DEFAULT_THEME_LAYOUT = {
  paper_bgcolor: '#0f172a',
  plot_bgcolor: '#0b1120',
  font: {
    family: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
    size: 11,
    color: '#94a3b8',
  },
  margin: { l: 50, r: 24, t: 40, b: 45 },
  xaxis: {
    gridcolor: '#1e293b',
    zerolinecolor: '#334155',
    tickfont: { color: '#64748b' },
  },
  yaxis: {
    gridcolor: '#1e293b',
    zerolinecolor: '#334155',
    tickfont: { color: '#64748b' },
  },
  legend: {
    font: { color: '#cbd5e1' },
    bgcolor: 'rgba(15, 23, 42, 0.8)',
    bordercolor: '#334155',
  },
  hoverlabel: {
    bgcolor: '#1e293b',
    bordercolor: '#06b6d4',
    font: { color: '#fff', family: 'ui-monospace, monospace' },
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
        borderRadius: '8px',
        overflow: 'hidden',
        ...style,
      }}
    />
  );
}
