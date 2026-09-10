import React, { useState } from 'react';
import PlotlyChart from './PlotlyChart';
import { parseHypothesesData } from '../../utils/visualizerData';
import EmptyState from '../ui/EmptyState';

const STAGE_OPTIONS = [
  { key: 's2_estimate', label: 'S2 · Modulation' },
  { key: 's4_recover', label: 'S4 · Interleaver' },
  { key: 's1_detect', label: 'S1 · Burstiness' },
  { key: 's3_receive', label: 'S3 · Phase Ambiguity' },
  { key: 's5_decode', label: 'S5 · FEC Code' },
  { key: 's6_frame', label: 'S6 · Framing' },
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
        <EmptyState icon="scale" title={`No Hypotheses for ${selectedStage}`}>
          Hypothesis ranking data is not available for this stage or the stage has not completed.
        </EmptyState>
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
            idx === parsed.scores.length - 1 ? '#3ecf8e' : 'rgba(77, 184, 216, 0.65)'
          ),
        },
        customdata: parsed.evidence,
        hovertemplate: '<b>%{y}</b><br>Confidence: %{x:.1f}%<br>Evidence: %{customdata}<extra></extra>',
      },
    ];

    const layout = {
      title: {
        text: `Hypothesis Ranking · ${selectedStage.toUpperCase()}`,
        font: { color: '#e8edf4', size: 12, weight: 600 },
        x: 0.02,
      },
      xaxis: {
        title: { text: 'Confidence Score (%)', font: { color: '#97a3b6', size: 11 } },
        range: [0, 105],
      },
      yaxis: {
        title: { text: 'Candidate Model', font: { color: '#97a3b6', size: 11 } },
        tickfont: { color: '#97a3b6', size: 11 },
      },
      margin: { l: 140, r: 24, t: 40, b: 40 },
    };

    return <PlotlyChart data={traces} layout={layout} style={{ minHeight: '300px' }} />;
  };

  return (
    <div>
      {/* Stage Selector Pills */}
      <div
        role="tablist"
        aria-label="Hypothesis stage selector"
        style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}
      >
        {STAGE_OPTIONS.map(opt => {
          const isActive = selectedStage === opt.key;
          const stg = stages.find(s => s.stage === opt.key);
          const count = stg?.hypotheses?.length ?? 0;

          return (
            <button
              key={opt.key}
              role="tab"
              aria-selected={isActive}
              onClick={() => setSelectedStage(opt.key)}
              className={`tab-btn${isActive ? ' is-active' : ''}`}
            >
              <span>{opt.label}</span>
              {count > 0 && <span className="tab-count">{count}</span>}
            </button>
          );
        })}
      </div>

      {renderContent()}
    </div>
  );
}
