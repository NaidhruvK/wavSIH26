import React from 'react';
import PlotlyChart from './PlotlyChart';
import { parsePsdData } from '../../utils/visualizerData';
import EmptyState from '../ui/EmptyState';
import MetricPill from '../ui/MetricPill';

export default function PsdPlot({ artifactData, stageValues }) {
  const parsed = parsePsdData(artifactData);

  if (!parsed) {
    return (
      <EmptyState icon="spectrum" title="PSD Artifact Unavailable">
        Spectral power data has not been generated for this run or stage S1 has not completed.
      </EmptyState>
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
      line: { color: '#4db8d8', width: 1.5 },
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
      line: { color: '#e0564d', width: 1.5, dash: 'dash' },
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
      font: { color: '#e0564d', size: 10 },
      bgcolor: 'rgba(9, 12, 18, 0.8)',
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
      arrowcolor: '#3ecf8e',
      font: { color: '#3ecf8e', size: 10 },
      bgcolor: 'rgba(9, 12, 18, 0.8)',
    });
  }

  const layout = {
    title: {
      text: 'S1 · Power Spectral Density (PSD)',
      font: { color: '#e8edf4', size: 12, weight: 600 },
      x: 0.02,
    },
    xaxis: {
      title: { text: 'Baseband Frequency (kHz)', font: { color: '#97a3b6', size: 11 } },
    },
    yaxis: {
      title: { text: 'Power (dB/Hz)', font: { color: '#97a3b6', size: 11 } },
    },
    shapes,
    annotations,
  };

  const snr = stageValues?.snr_db;
  const occBw = stageValues?.occupied_bw_hz;

  return (
    <div>
      {/* Metric readouts */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
        <MetricPill label="Peak Power" value={`${parsed.peakPsd?.toFixed(1)} dB`} tone="ok" />
        <MetricPill label="Peak Freq" value={`${peakFreqKhz.toFixed(2)} kHz`} tone="accent" />
        {snr !== undefined && snr !== null && (
          <MetricPill label="Est. SNR" value={`${Number(snr).toFixed(1)} dB`} />
        )}
        {occBw !== undefined && occBw !== null && (
          <MetricPill label="Occupied BW" value={`${(Number(occBw) / 1000).toFixed(1)} kHz`} />
        )}
        <MetricPill
          label="Points"
          value={`${parsed.renderedPoints} / ${parsed.totalPoints}`}
          tone="muted"
          style={{ marginLeft: 'auto' }}
        />
      </div>

      <PlotlyChart data={traces} layout={layout} />
    </div>
  );
}
