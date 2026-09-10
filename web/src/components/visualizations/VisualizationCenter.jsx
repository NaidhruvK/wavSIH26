import React, { useState, useEffect } from 'react';
import PsdPlot from './PsdPlot';
import WaterfallPlot from './WaterfallPlot';
import ConstellationPlot from './ConstellationPlot';
import RankProfilePlot from './RankProfilePlot';
import EnvelopePlot from './EnvelopePlot';
import HypothesisChart from './HypothesisChart';
import { getArtifactUrl } from '../../api';
import Icon from '../ui/icons';
import SectionHeader from '../ui/SectionHeader';

const TABS = [
  { id: 'psd', label: 'PSD Spectrum', stage: 'S1', icon: 'spectrum' },
  { id: 'waterfall', label: 'Waterfall', stage: 'S1', icon: 'layers' },
  { id: 'constellation', label: 'Constellation', stage: 'S3', icon: 'crosshair' },
  { id: 'rank_profile', label: 'Rank Profile', stage: 'S4', icon: 'barChart' },
  { id: 'envelope', label: 'Operating Envelope', stage: null, icon: 'boundary' },
  { id: 'hypotheses', label: 'Hypotheses', stage: null, icon: 'scale' },
];

export default function VisualizationCenter({ runId, report, envelope }) {
  const [activeTab, setActiveTab] = useState('psd');
  const [artifactsData, setArtifactsData] = useState({});
  const [isLoadingArtifacts, setIsLoadingArtifacts] = useState(false);

  // Extract stage objects from report
  const stages = report?.stages || [];
  const s1Stage = stages.find(s => s.stage === 's1_detect');
  const s3Stage = stages.find(s => s.stage === 's3_receive');
  const s4Stage = stages.find(s => s.stage === 's4_recover');

  // Load artifacts when runId or stages change
  useEffect(() => {
    if (!runId) {
      setArtifactsData({});
      return;
    }

    let isMounted = true;
    setIsLoadingArtifacts(true);

    async function fetchArtifact(artName) {
      try {
        const url = getArtifactUrl(runId, artName);
        const res = await fetch(url);
        if (!res.ok) return null;
        const contentType = res.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
          return await res.json();
        }
        // If image or non-json, return url
        return { isImage: true, url };
      } catch (err) {
        return null;
      }
    }

    // The artifact endpoint serves files by their stored basename (e.g. "psd"
    // from reports/artifacts/<run>/psd.json), not by the stage's artifact key
    // (e.g. "psd_plot"). Derive the served name from the declared path.
    function artifactNameFrom(stage, key, fallback) {
      const declaredPath = stage?.artifacts?.[key];
      if (typeof declaredPath === 'string' && declaredPath) {
        const base = declaredPath.split(/[\\/]/).pop();
        if (base) return base.replace(/\.json$/i, '');
      }
      return fallback;
    }

    async function loadAll() {
      const s1ArtKey = artifactNameFrom(s1Stage, 'psd_plot', 'psd');
      const s1WfKey = artifactNameFrom(s1Stage, 'waterfall_plot', 'waterfall');
      const s3ArtKey = artifactNameFrom(s3Stage, 'constellation_plot', 'constellation');
      const s4ArtKey = artifactNameFrom(s4Stage, 'rank_profile_plot', 'rank_profile');

      const [psd, waterfall, constellation, rankProfile] = await Promise.all([
        fetchArtifact(s1ArtKey),
        fetchArtifact(s1WfKey),
        fetchArtifact(s3ArtKey),
        fetchArtifact(s4ArtKey),
      ]);

      if (isMounted) {
        setArtifactsData({
          psd,
          waterfall,
          constellation,
          rankProfile,
        });
        setIsLoadingArtifacts(false);
      }
    }

    loadAll();

    return () => {
      isMounted = false;
    };
  }, [runId, s1Stage?.status, s3Stage?.status, s4Stage?.status]);

  const renderActivePlot = () => {
    switch (activeTab) {
      case 'psd':
        return (
          <PsdPlot
            artifactData={artifactsData.psd?.isImage ? null : artifactsData.psd}
            stageValues={s1Stage?.values}
          />
        );
      case 'waterfall':
        return (
          <WaterfallPlot
            artifactData={artifactsData.waterfall?.isImage ? null : artifactsData.waterfall}
            imageUrl={artifactsData.waterfall?.isImage ? artifactsData.waterfall.url : null}
            stageValues={s1Stage?.values}
          />
        );
      case 'constellation':
        return (
          <ConstellationPlot
            artifactData={artifactsData.constellation?.isImage ? null : artifactsData.constellation}
            imageUrl={artifactsData.constellation?.isImage ? artifactsData.constellation.url : null}
            stageValues={s3Stage?.values}
          />
        );
      case 'rank_profile':
        return (
          <RankProfilePlot
            artifactData={artifactsData.rankProfile?.isImage ? null : artifactsData.rankProfile}
            imageUrl={artifactsData.rankProfile?.isImage ? artifactsData.rankProfile.url : null}
            stageValues={s4Stage?.values}
          />
        );
      case 'envelope':
        return (
          <EnvelopePlot
            envelope={envelope}
            runReport={report}
          />
        );
      case 'hypotheses':
        return (
          <HypothesisChart
            report={report}
          />
        );
      default:
        return null;
    }
  };

  return (
    <section className="panel panel--ticks panel--pad" style={{ marginBottom: 'var(--sp-5)' }}>
      <SectionHeader
        icon="waveform"
        title="Signal Visualization"
        caption="Spectral, demodulation, coding analysis & operating envelope."
      >
        {runId && (
          <span className="metric-pill">
            <span className="mp-label">Source Run</span>
            <span className="mp-value" style={{ color: 'var(--accent-strong)' }}>{runId}</span>
          </span>
        )}
      </SectionHeader>

      {/* Tabs Navigation */}
      <div
        role="tablist"
        aria-label="Visualization panels"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 4,
          borderBottom: '1px solid var(--border)',
          paddingBottom: 10,
          marginBottom: 'var(--sp-4)',
        }}
      >
        {TABS.map(tab => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveTab(tab.id)}
              className={`tab-btn${isActive ? ' is-active' : ''}`}
            >
              <Icon name={tab.icon} size={12} />
              <span>{tab.label}</span>
              {tab.stage && (
                <span className="tab-count">{tab.stage}</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Content Area */}
      <div>
        {isLoadingArtifacts && runId && activeTab !== 'envelope' && activeTab !== 'hypotheses' ? (
          <div
            className="inset"
            role="status"
            style={{
              padding: 40,
              textAlign: 'center',
              color: 'var(--text-secondary)',
              fontSize: 12,
              fontFamily: 'var(--font-mono)',
            }}
          >
            <span className="spin-anim" style={{ display: 'inline-flex', color: 'var(--accent)', marginBottom: 8 }}>
              <Icon name="reset" size={20} />
            </span>
            <div>Loading stage artifacts…</div>
          </div>
        ) : (
          renderActivePlot()
        )}
      </div>
    </section>
  );
}
