import React from 'react';

export default function Header({ health, onOpenEnvelope, onOpenRegistry }) {
  const isHealthy = health?.status === 'healthy';

  return (
    <header style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '16px 24px',
      borderBottom: '1px solid var(--border)',
      background: 'rgba(17, 23, 38, 0.7)',
      backdropFilter: 'blur(8px)',
      position: 'sticky',
      top: 0,
      zIndex: 40,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{
          width: '38px',
          height: '38px',
          borderRadius: '8px',
          background: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontWeight: 800,
          fontSize: '18px',
          color: '#ffffff',
          letterSpacing: '1px',
          boxShadow: '0 0 16px rgba(6, 182, 212, 0.4)',
        }}>
          R
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ fontSize: '18px', fontWeight: 800, letterSpacing: '0.5px', color: '#fff' }}>
              RAAYA
            </h1>
            <span style={{
              fontSize: '11px',
              fontFamily: 'var(--font-mono)',
              background: 'rgba(6, 182, 212, 0.12)',
              color: 'var(--cyan)',
              border: '1px solid rgba(6, 182, 212, 0.3)',
              padding: '2px 8px',
              borderRadius: '999px',
              fontWeight: 600,
            }}>
              SIH26147
            </span>
          </div>
          <p style={{ fontSize: '12px', color: 'var(--text-dim)', fontWeight: 500 }}>
            Blind RF Demodulation, Rank Collapse & Telemetry Recovery
          </p>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {/* Operating Envelope Trigger */}
        <button
          onClick={onOpenEnvelope}
          style={{
            background: 'var(--bg-input)',
            border: '1px solid var(--border)',
            color: 'var(--text-muted)',
            padding: '6px 12px',
            borderRadius: '6px',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--cyan)'; e.currentTarget.style.color = '#fff'; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-muted)'; }}
        >
          <span>📐</span> Envelope
        </button>

        {/* Registry Drawer Trigger */}
        <button
          onClick={onOpenRegistry}
          style={{
            background: 'var(--bg-input)',
            border: '1px solid var(--border)',
            color: 'var(--text-muted)',
            padding: '6px 12px',
            borderRadius: '6px',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--cyan)'; e.currentTarget.style.color = '#fff'; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-muted)'; }}
        >
          <span>🔌</span> Registries
        </button>

        {/* Service Health Indicator */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          background: isHealthy ? 'rgba(16, 185, 129, 0.08)' : 'rgba(244, 63, 94, 0.08)',
          border: `1px solid ${isHealthy ? 'rgba(16, 185, 129, 0.3)' : 'rgba(244, 63, 94, 0.3)'}`,
          padding: '4px 12px',
          borderRadius: '999px',
          fontSize: '12px',
          fontWeight: 600,
          color: isHealthy ? 'var(--emerald)' : 'var(--rose)',
        }}>
          <span style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: isHealthy ? 'var(--emerald)' : 'var(--rose)',
            boxShadow: `0 0 8px ${isHealthy ? 'var(--emerald)' : 'var(--rose)'}`,
          }} />
          <span>{isHealthy ? 'BACKEND READY' : 'OFFLINE'}</span>
        </div>
      </div>
    </header>
  );
}
