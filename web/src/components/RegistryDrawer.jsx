import React from 'react';
import Modal from './ui/Modal';

function PluginList({ title, items, fallback }) {
  return (
    <div>
      <h4 className="t-label" style={{ fontSize: 10, marginBottom: 8 }}>{title}</h4>
      {items.length === 0 ? (
        <div className="t-caption" style={{ fontSize: 12, fontStyle: 'italic' }}>{fallback}</div>
      ) : (
        items.map((item, i) => (
          <div
            key={i}
            className="t-data"
            style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}
          >
            <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{item.name}</span>
            <span style={{ color: 'var(--text-tertiary)' }}> · {item.module}</span>
          </div>
        ))
      )}
    </div>
  );
}

export default function RegistryDrawer({ registry, onClose }) {
  if (!registry) return null;

  const counts = registry.counts || {};
  const modulations = registry.modulations || [];
  const interleavers = registry.interleavers || [];
  const codes = registry.codes || [];

  const summary = [
    { label: 'Modulations', value: counts.modulations || 0, tone: 'var(--accent-strong)' },
    { label: 'Interleavers', value: counts.interleavers || 0, tone: 'var(--ok)' },
    { label: 'Codes', value: counts.codes || 0, tone: 'var(--warn)' },
  ];

  return (
    <Modal
      title="Plugin Registries Introspection"
      subtitle="Live registration tables for modular modulation, interleaver, and code algorithms."
      onClose={onClose}
      maxWidth={620}
    >
      {/* Counts summary */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 20 }}>
        {summary.map(({ label, value, tone }) => (
          <div key={label} className="inset" style={{ padding: 10 }}>
            <div className="t-label" style={{ fontSize: 9, marginBottom: 3 }}>{label}</div>
            <div className="t-data" style={{ fontSize: 16, fontWeight: 700, color: tone }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      {/* Plugin lists */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <PluginList
          title="Modulations"
          items={modulations}
          fallback="No external plugins registered (built-in S3 receiver active)"
        />
        <PluginList
          title="Interleavers"
          items={interleavers}
          fallback="No external plugins registered (built-in S4 rank collapse active)"
        />
        <PluginList
          title="Error-Correcting Codes"
          items={codes}
          fallback="No external plugins registered (built-in S5 Viterbi active)"
        />
      </div>
    </Modal>
  );
}
