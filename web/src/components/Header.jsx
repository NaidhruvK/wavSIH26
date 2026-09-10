import React, { useEffect, useState } from 'react';
import Icon from './ui/icons';

function useUtcClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getUTCFullYear()}-${pad(now.getUTCMonth() + 1)}-${pad(now.getUTCDate())} ${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())}`;
}

export default function Header({ health, onOpenEnvelope, onOpenRegistry }) {
  const isHealthy = health?.status === 'healthy';
  const utc = useUtcClock();

  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        flexWrap: 'wrap',
        padding: '12px 20px',
        borderBottom: '1px solid var(--border)',
        background: 'rgba(9, 12, 18, 0.82)',
        backdropFilter: 'blur(8px)',
        position: 'sticky',
        top: 0,
        zIndex: 40,
      }}
    >
      {/* Brand block */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div
          aria-hidden="true"
          style={{
            width: 36,
            height: 36,
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--accent-border)',
            background: 'var(--accent-dim)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--accent-strong)',
          }}
        >
          <Icon name="antenna" size={19} />
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h1
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 17,
                fontWeight: 700,
                letterSpacing: '0.18em',
                color: 'var(--text-primary)',
              }}
            >
              RAAYA
            </h1>
            <span className="badge badge--accent">SIH26147</span>
          </div>
          <p className="t-caption" style={{ fontSize: 11, marginTop: 1 }}>
            Blind RF Demodulation · Rank Collapse · Telemetry Recovery
          </p>
        </div>
      </div>

      {/* Right cluster: clock, config triggers, health */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span
          className="t-data"
          title="Coordinated Universal Time"
          style={{
            fontSize: 11,
            color: 'var(--text-tertiary)',
            letterSpacing: '0.05em',
            padding: '4px 10px',
            borderRight: '1px solid var(--border)',
          }}
        >
          {utc} UTC
        </span>

        <button onClick={onOpenEnvelope} className="btn">
          <Icon name="boundary" size={13} />
          Envelope
        </button>

        <button onClick={onOpenRegistry} className="btn">
          <Icon name="plug" size={13} />
          Registries
        </button>

        <span
          className={`badge badge--${isHealthy ? 'ok' : 'danger'}`}
          role="status"
          aria-live="polite"
          style={{ padding: '5px 10px' }}
        >
          <span className={`led led--${isHealthy ? 'ok' : 'danger'}${isHealthy ? '' : ' led--pulse'}`} />
          {isHealthy ? 'BACKEND READY' : 'OFFLINE'}
        </span>
      </div>
    </header>
  );
}
