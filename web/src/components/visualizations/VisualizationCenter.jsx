import React, { useState, useEffect } from 'react';
import PsdPlot from './PsdPlot';
import WaterfallPlot from './WaterfallPlot';
import ConstellationPlot from './ConstellationPlot';
import RankProfilePlot from './RankProfilePlot';
import EnvelopePlot from './EnvelopePlot';
import HypothesisChart from './HypothesisChart';
import { getArtifactUrl } from '../../api';

const TABS = [
  { id: 'psd', label: 'PSD Spectrum (S1)', icon: '📡' },
  { id: 'waterfall', label: 'Waterfall / Spectrogram (S1)', icon: '🌊' },
  { id: 'constellation', label: 'Constellation (S3)', icon: '🎯' },
  { id: 'rank_profile', label: 'Rank Profile (S4)', icon: '📉' },
  { id: 'envelope', label: 'Operating Envelope', icon: '📈' },
  { id: 'hypotheses', label: 'Hypotheses Ranking', icon: '⚖️' },
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

    async function loadAll() {
      // Check stage declared artifact keys or standard names
      const s1ArtKey = s1Stage?.artifacts?.psd_plot ? 'psd_plot' : 'psd';
      const s1WfKey = s1Stage?.artifacts?.waterfall_plot ? 'waterfall_plot' : 'waterfall';
      const s3ArtKey = s3Stage?.artifacts?.constellation_plot ? 'constellation_plot' : 'constellation';
      const s4ArtKey = s4Stage?.artifacts?.rank_profile_plot ? 'rank_profile_plot' : 'rank_profile';

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
    <section style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: '10px',
      padding: '20px',
      marginBottom: '24px',
      boxShadow: '0 4px 12px rgba(0, 0, 0, 0.2)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '16px',
        flexWrap: 'wrap',
        gap: '10px',
      }}>
        <div>
          <h2 style={{ fontSize: '15px', fontWeight: 800, color: '#fff', letterSpacing: '0.3px', margin: 0 }}>
            RF TELEMETRY & SIGNAL VISUALIZATION
          </h2>
          <span style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '2px', display: 'block' }}>
            Interactive Spectral, Demodulation, Coding Analysis & Operating Envelope
          </span>
        </div>

        {runId && (
          <div style={{
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            background: 'var(--bg-input)',
            padding: '4px 10px',
            borderRadius: '4px',
            color: 'var(--cyan)',
            border: '1px solid rgba(6, 182, 212, 0.2)',
          }}>
            Source Run: {runId}
          </div>
        )}
      </div>

      {/* Tabs Navigation */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '6px',
        borderBottom: '1px solid var(--border)',
        paddingBottom: '12px',
        marginBottom: '16px',
      }}>
        {TABS.map(tab => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                background: isActive ? 'var(--cyan-glow)' : 'transparent',
                border: `1px solid ${isActive ? 'var(--cyan)' : 'transparent'}`,
                color: isActive ? '#fff' : 'var(--text-dim)',
                padding: '6px 14px',
                borderRadius: '6px',
                fontSize: '12px',
                fontWeight: isActive ? 700 : 500,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                transition: 'all 0.15s ease',
              }}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Content Area */}
      <div>
        {isLoadingArtifacts && runId && activeTab !== 'envelope' && activeTab !== 'hypotheses' ? (
          <div style={{
            padding: '40px',
            textAlign: 'center',
            color: 'var(--cyan)',
            fontSize: '12px',
            fontFamily: 'var(--font-mono)',
          }}>
            <div style={{ fontSize: '24px', marginBottom: '8px', animation: 'spin 1.5s linear infinite' }}>⚙️</div>
            Loading Stage Artifacts...
          </div>
        ) : (
          renderActivePlot()
        )}
      </div>
    </section>
  );
}
