import React from 'react';
import PlotlyChart from './PlotlyChart';

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
        title: { text: 'dB', font: { color: '#94a3b8', size: 10 } },
        tickfont: { color: '#94a3b8', size: 9 },
      },
    };

    const layout = {
      title: {
        text: 'S1 • Spectrogram / Waterfall Matrix',
        font: { color: '#fff', size: 13, weight: 700 },
        x: 0.02,
      },
      xaxis: {
        title: { text: 'Baseband Frequency (kHz)', font: { color: '#94a3b8', size: 11 } },
      },
      yaxis: {
        title: { text: 'Time (s)', font: { color: '#94a3b8', size: 11 } },
      },
    };

    return (
      <div>
        <div style={{ marginBottom: '10px', fontSize: '11px', color: 'var(--text-dim)' }}>
          2D Spectrogram Heatmap • Real-time spectral energy density across time and frequency.
        </div>
        <PlotlyChart data={[trace]} layout={layout} />
      </div>
    );
  }

  // If raster image URL is available (e.g. from artifact endpoint or reports/artifacts)
  if (imageUrl) {
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
            S1 • Spectrogram Artifact
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
          alt="Waterfall Spectrogram"
          style={{
            maxWidth: '100%',
            height: 'auto',
            maxHeight: '420px',
            borderRadius: '6px',
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
    <div style={{
      background: 'var(--bg-input)',
      padding: '36px 20px',
      textAlign: 'center',
      borderRadius: '8px',
      color: 'var(--text-dim)',
      fontSize: '13px',
    }}>
      <div style={{ fontSize: '24px', marginBottom: '8px' }}>🌊</div>
      <div style={{ fontWeight: 600, color: '#fff', marginBottom: '4px' }}>
        Spectrogram Artifact Unavailable
      </div>
      <div style={{ maxWidth: '560px', margin: '0 auto', lineHeight: '1.5' }}>
        Stage S1 completed with 1D Welch PSD spectrum. A 2D waterfall matrix or raster artifact
        was not generated for this run. Refer to the <strong>Power Spectral Density (PSD)</strong> tab
        for calibrated frequency and power distribution.
      </div>
    </div>
  );
}
