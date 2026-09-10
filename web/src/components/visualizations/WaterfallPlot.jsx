import React from 'react';
import PlotlyChart from './PlotlyChart';
import EmptyState from '../ui/EmptyState';
import Icon from '../ui/icons';

export default function WaterfallPlot({ artifactData, imageUrl, stageValues }) {
  // If artifact is a 2D matrix JSON
  const is2DMatrix = artifactData && typeof artifactData === 'object' && (
    (Array.isArray(artifactData.power) && Array.isArray(artifactData.power[0])) ||
    (Array.isArray(artifactData.z) && Array.isArray(artifactData.z[0])) ||
    (Array.isArray(artifactData.spectrogram) && Array.isArray(artifactData.spectrogram[0]))
  );

  if (is2DMatrix) {
    const z = artifactData.power || artifactData.z || artifactData.spectrogram;
    const x = (artifactData.freqs || artifactData.frequencies || artifactData.x || []).map(f => f / 1000.0);
    const y = artifactData.time || artifactData.timestamps || artifactData.y || [];

    const trace = {
      z,
      x: x.length > 0 ? x : undefined,
      y: y.length > 0 ? y : undefined,
      type: 'heatmap',
      colorscale: 'Viridis',
      hovertemplate: 'Freq: %{x:.2f} kHz<br>Time: %{y:.2f} s<br>Power: %{z:.1f} dB<extra></extra>',
      colorbar: {
        title: { text: 'dB', font: { color: '#97a3b6', size: 10 } },
        tickfont: { color: '#97a3b6', size: 9 },
      },
    };

    const layout = {
      title: {
        text: 'S1 · Spectrogram / Waterfall Matrix',
        font: { color: '#e8edf4', size: 12, weight: 600 },
        x: 0.02,
      },
      xaxis: {
        title: { text: 'Baseband Frequency (kHz)', font: { color: '#97a3b6', size: 11 } },
      },
      yaxis: {
        title: { text: 'Time (s)', font: { color: '#97a3b6', size: 11 } },
      },
    };

    return (
      <div>
        <div className="t-caption" style={{ marginBottom: 10, fontSize: 11 }}>
          2D spectrogram heatmap · spectral energy density across time and frequency.
        </div>
        <PlotlyChart data={[trace]} layout={layout} />
      </div>
    );
  }

  // If raster image URL is available (e.g. from artifact endpoint or reports/artifacts)
  if (imageUrl) {
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
            S1 · Spectrogram Artifact
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
          alt="Waterfall Spectrogram"
          style={{
            maxWidth: '100%',
            height: 'auto',
            maxHeight: 420,
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border)',
          }}
          onError={e => {
            e.target.style.display = 'none';
          }}
        />
      </div>
    );
  }

  // Graceful fallback for missing artifact
  return (
    <EmptyState icon="layers" title="Spectrogram Artifact Unavailable">
      Stage S1 completed with 1D Welch PSD spectrum. A 2D waterfall matrix or raster artifact
      was not generated for this run. Refer to the <strong>PSD Spectrum</strong> tab
      for calibrated frequency and power distribution.
    </EmptyState>
  );
}
