import React from 'react';

export default function RegistryDrawer({ registry, onClose }) {
  if (!registry) return null;

  const counts = registry.counts || {};
  const modulations = registry.modulations || [];
  const interleavers = registry.interleavers || [];
  const codes = registry.codes || [];

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0, 0, 0, 0.75)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 50,
      padding: '20px',
    }}>
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: '12px',
        width: '100%',
        maxWidth: '620px',
        maxHeight: '85vh',
        overflowY: 'auto',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.5)',
        padding: '24px',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <h2 style={{ fontSize: '16px', fontWeight: 800, color: '#fff' }}>
              PLUGIN REGISTRIES INTROSPECTION
            </h2>
            <p style={{ fontSize: '12px', color: 'var(--text-dim)' }}>
              Live registration tables for modular modulation, interleaver, and code algorithms.
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-dim)',
              fontSize: '20px',
              cursor: 'pointer',
            }}
          >
            ✕
          </button>
        </div>

        {/* Counts summary */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: '10px',
          marginBottom: '20px',
        }}>
          <div style={{ background: 'var(--bg-input)', padding: '10px', borderRadius: '6px', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontWeight: 600 }}>MODULATIONS</div>
            <div style={{ fontSize: '16px', fontWeight: 800, color: 'var(--cyan)', fontFamily: 'var(--font-mono)' }}>
              {counts.modulations || 0}
            </div>
          </div>
          <div style={{ background: 'var(--bg-input)', padding: '10px', borderRadius: '6px', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontWeight: 600 }}>INTERLEAVERS</div>
            <div style={{ fontSize: '16px', fontWeight: 800, color: 'var(--emerald)', fontFamily: 'var(--font-mono)' }}>
              {counts.interleavers || 0}
            </div>
          </div>
          <div style={{ background: 'var(--bg-input)', padding: '10px', borderRadius: '6px', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontWeight: 600 }}>CODES</div>
            <div style={{ fontSize: '16px', fontWeight: 800, color: 'var(--amber)', fontFamily: 'var(--font-mono)' }}>
              {counts.codes || 0}
            </div>
          </div>
        </div>

        {/* Plugin lists */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div>
            <h4 style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '8px' }}>
              MODULATIONS
            </h4>
            {modulations.length === 0 ? (
              <div style={{ fontSize: '12px', color: 'var(--text-dim)', fontStyle: 'italic' }}>No external plugins registered (built-in S3 receiver active)</div>
            ) : (
              modulations.map((m, i) => (
                <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: '12px', fontFamily: 'var(--font-mono)' }}>
                  <span style={{ color: '#fff', fontWeight: 700 }}>{m.name}</span> • <span style={{ color: 'var(--text-dim)' }}>{m.module}</span>
                </div>
              ))
            )}
          </div>

          <div>
            <h4 style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '8px' }}>
              INTERLEAVERS
            </h4>
            {interleavers.length === 0 ? (
              <div style={{ fontSize: '12px', color: 'var(--text-dim)', fontStyle: 'italic' }}>No external plugins registered (built-in S4 rank collapse active)</div>
            ) : (
              interleavers.map((it, i) => (
                <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: '12px', fontFamily: 'var(--font-mono)' }}>
                  <span style={{ color: '#fff', fontWeight: 700 }}>{it.name}</span> • <span style={{ color: 'var(--text-dim)' }}>{it.module}</span>
                </div>
              ))
            )}
          </div>

          <div>
            <h4 style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '8px' }}>
              ERROR-CORRECTING CODES
            </h4>
            {codes.length === 0 ? (
              <div style={{ fontSize: '12px', color: 'var(--text-dim)', fontStyle: 'italic' }}>No external plugins registered (built-in S5 Viterbi active)</div>
            ) : (
              codes.map((c, i) => (
                <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: '12px', fontFamily: 'var(--font-mono)' }}>
                  <span style={{ color: '#fff', fontWeight: 700 }}>{c.name}</span> • <span style={{ color: 'var(--text-dim)' }}>{c.module}</span>
                </div>
              ))
            )}
          </div>
        </div>

        <div style={{ marginTop: '20px', textAlign: 'right' }}>
          <button
            onClick={onClose}
            style={{
              background: 'var(--bg-input)',
              border: '1px solid var(--border)',
              color: '#fff',
              padding: '8px 18px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
