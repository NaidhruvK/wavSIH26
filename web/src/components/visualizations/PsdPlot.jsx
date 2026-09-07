import React from 'react';
import PlotlyChart from './PlotlyChart';
import { parsePsdData } from '../../utils/visualizerData';

export default function PsdPlot({ artifactData, stageValues }) {
  const parsed = parsePsdData(artifactData);

  if (!parsed) {
    return (
      <div style={{
        background: 'var(--bg-input)',
        padding: '36px 20px',
        textAlign: 'center',
        borderRadius: '8px',
        color: 'var(--text-dim)',
        fontSize: '13px',
      }}>
        <div style={{ fontSize: '24px', marginBottom: '8px' }}>📡</div>
        <div style={{ fontWeight: 600, color: '#fff', marginBottom: '4px' }}>
          PSD Artifact Unavailable
        </div>
        <div>
          Spectral power data has not been generated for this run or stage S1 has not completed.
        </div>
      </div>
    );
  }

  // Convert Hz to kHz for cleaner axis readout
  const freqsKhz = parsed.freqs.map(f => f / 1000.0);
  const peakFreqKhz = parsed.peakFreq / 1000.0;

  const traces = [
    {
      x: freqsKhz,
      y: parsed.psdDb,
      type: 'scatter',
      mode: 'lines',
      name: 'Power Spectral Density',
      line: { color: '#06b6d4', width: 1.5 },
      hovertemplate: 'Freq: %{x:.2f} kHz<br>Power: %{y:.1f} dB<extra></extra>',
    },
  ];

  const shapes = [];
  const annotations = [];

  // Noise floor horizontal line
  const noiseFloor = parsed.noiseFloorDb ?? stageValues?.noise_floor_db;
  if (typeof noiseFloor === 'number') {
    shapes.push({
      type: 'line',
      x0: freqsKhz[0],
      x1: freqsKhz[freqsKhz.length - 1],
      y0: noiseFloor,
      y1: noiseFloor,
      line: { color: '#f43f5e', width: 1.5, dash: 'dash' },
    });
    annotations.push({
      x: freqsKhz[freqsKhz.length - 1],
      y: noiseFloor,
      xref: 'x',
      yref: 'y',
      text: `Noise Floor (${noiseFloor.toFixed(1)} dB)`,
      showarrow: false,
      xanchor: 'right',
      yanchor: 'bottom',
      font: { color: '#f43f5e', size: 10 },
      bgcolor: 'rgba(15, 23, 42, 0.8)',
    });
  }

  // Peak marker annotation
  if (parsed.peakPsd !== null) {
    annotations.push({
      x: peakFreqKhz,
      y: parsed.peakPsd,
      xref: 'x',
      yref: 'y',
      text: `Peak (${parsed.peakPsd.toFixed(1)} dB)`,
      showarrow: true,
      arrowhead: 2,
      arrowsize: 1,
      arrowwidth: 1,
      arrowcolor: '#10b981',
      font: { color: '#10b981', size: 10 },
      bgcolor: 'rgba(15, 23, 42, 0.8)',
    });
  }

  const layout = {
    title: {
      text: 'S1 • Power Spectral Density (PSD)',
      font: { color: '#fff', size: 13, weight: 700 },
      x: 0.02,
    },
    xaxis: {
      title: { text: 'Baseband Frequency (kHz)', font: { color: '#94a3b8', size: 11 } },
    },
    yaxis: {
      title: { text: 'Power (dB/Hz)', font: { color: '#94a3b8', size: 11 } },
    },
    shapes,
    annotations,
  };

  const snr = stageValues?.snr_db;
  const occBw = stageValues?.occupied_bw_hz;

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
        <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
          <span style={{ color: 'var(--text-dim)' }}>Peak Power: </span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--emerald)', fontWeight: 700 }}>
            {parsed.peakPsd?.toFixed(1)} dB
          </span>
        </div>
        <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
          <span style={{ color: 'var(--text-dim)' }}>Peak Freq: </span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan)', fontWeight: 700 }}>
            {peakFreqKhz.toFixed(2)} kHz
          </span>
        </div>
        {snr !== undefined && snr !== null && (
          <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
            <span style={{ color: 'var(--text-dim)' }}>Estimated SNR: </span>
            <span style={{ fontFamily: 'var(--font-mono)', color: '#fff', fontWeight: 700 }}>
              {Number(snr).toFixed(1)} dB
            </span>
          </div>
        )}
        {occBw !== undefined && occBw !== null && (
          <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px' }}>
            <span style={{ color: 'var(--text-dim)' }}>Occupied BW: </span>
            <span style={{ fontFamily: 'var(--font-mono)', color: '#fff', fontWeight: 700 }}>
              {(Number(occBw) / 1000).toFixed(1)} kHz
            </span>
          </div>
        )}
        <div style={{ background: 'var(--bg-input)', padding: '6px 10px', borderRadius: '4px', marginLeft: 'auto' }}>
          <span style={{ color: 'var(--text-dim)' }}>Points Rendered: </span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
            {parsed.renderedPoints} / {parsed.totalPoints}
          </span>
        </div>
      </div>

      <PlotlyChart data={traces} layout={layout} />
    </div>
  );
}
