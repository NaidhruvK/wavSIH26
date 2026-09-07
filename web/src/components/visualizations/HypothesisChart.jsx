import React, { useState } from 'react';
import PlotlyChart from './PlotlyChart';
import { parseHypothesesData } from '../../utils/visualizerData';

const STAGE_OPTIONS = [
  { key: 's2_estimate', label: 'S2 • Modulation' },
  { key: 's4_recover', label: 'S4 • Interleaver' },
  { key: 's1_detect', label: 'S1 • Burstiness' },
  { key: 's3_receive', label: 'S3 • Phase Ambiguity' },
  { key: 's5_decode', label: 'S5 • FEC Code' },
  { key: 's6_frame', label: 'S6 • Framing' },
];

export default function HypothesisChart({ report }) {
  const [selectedStage, setSelectedStage] = useState('s2_estimate');

  const stages = report?.stages || [];
  const stageObj = stages.find(s => s.stage === selectedStage);
  const hypotheses = stageObj?.hypotheses || [];

  const parsed = parseHypothesesData(hypotheses);

  const renderContent = () => {
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
          <div style={{ fontSize: '24px', marginBottom: '8px' }}>⚖️</div>
          <div style={{ fontWeight: 600, color: '#fff', marginBottom: '4px' }}>
            No Hypotheses for {selectedStage}
          </div>
          <div>
            Hypothesis ranking data is not available for this stage or the stage has not completed.
          </div>
        </div>
      );
    }

    const traces = [
      {
        y: parsed.labels,
        x: parsed.scores,
        type: 'bar',
        orientation: 'h',
        marker: {
          color: parsed.scores.map((s, idx) =>
            idx === parsed.scores.length - 1 ? '#10b981' : 'rgba(6, 182, 212, 0.75)'
          ),
        },
        customdata: parsed.evidence,
        hovertemplate: '<b>%{y}</b><br>Confidence: %{x:.1f}%<br>Evidence: %{customdata}<extra></extra>',
      },
    ];

    const layout = {
      title: {
        text: `Hypothesis Ranking • ${selectedStage.toUpperCase()}`,
        font: { color: '#fff', size: 13, weight: 700 },
        x: 0.02,
      },
      xaxis: {
        title: { text: 'Confidence Score (%)', font: { color: '#94a3b8', size: 11 } },
        range: [0, 105],
      },
      yaxis: {
        title: { text: 'Candidate Model', font: { color: '#94a3b8', size: 11 } },
        tickfont: { color: '#cbd5e1', size: 11 },
      },
      margin: { l: 140, r: 24, t: 40, b: 40 },
    };

    return <PlotlyChart data={traces} layout={layout} style={{ minHeight: '300px' }} />;
  };

  return (
    <div>
      {/* Stage Selector Pills */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '8px',
        marginBottom: '14px',
      }}>
        {STAGE_OPTIONS.map(opt => {
          const isActive = selectedStage === opt.key;
          const stg = stages.find(s => s.stage === opt.key);
          const count = stg?.hypotheses?.length ?? 0;

          return (
            <button
              key={opt.key}
              onClick={() => setSelectedStage(opt.key)}
              style={{
                background: isActive ? 'rgba(6, 182, 212, 0.15)' : 'var(--bg-input)',
                border: `1px solid ${isActive ? 'var(--cyan)' : 'var(--border)'}`,
                color: isActive ? '#fff' : 'var(--text-dim)',
                padding: '5px 12px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <span>{opt.label}</span>
              {count > 0 && (
                <span style={{
                  background: isActive ? 'var(--cyan)' : '#334155',
                  color: isActive ? '#0b1120' : '#94a3b8',
                  padding: '1px 5px',
                  borderRadius: '10px',
                  fontSize: '9px',
                  fontWeight: 800,
                }}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {renderContent()}
    </div>
  );
}
