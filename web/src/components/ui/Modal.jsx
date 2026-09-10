import React, { useEffect, useRef } from 'react';
import Icon from './icons';

/**
 * Accessible modal shell: Esc to close, backdrop click, focus management,
 * role="dialog". Shared by the Envelope and Registry overlays.
 */
export default function Modal({ title, subtitle, onClose, maxWidth = 680, children }) {
  const closeBtnRef = useRef(null);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    closeBtnRef.current?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(4, 6, 10, 0.78)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 50,
        padding: 20,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="panel panel--ticks enter-anim"
        style={{
          width: '100%',
          maxWidth,
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: 'var(--shadow-overlay)',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 12,
            padding: '18px 20px 14px',
            borderBottom: '1px solid var(--border)',
          }}
        >
          <div>
            <h2 className="t-section">{title}</h2>
            {subtitle && (
              <p className="t-caption" style={{ marginTop: 3 }}>{subtitle}</p>
            )}
          </div>
          <button
            ref={closeBtnRef}
            onClick={onClose}
            className="btn btn--ghost btn--icon"
            aria-label="Close dialog"
          >
            <Icon name="x" size={14} />
          </button>
        </div>

        <div style={{ padding: 20, overflowY: 'auto' }}>
          {children}
        </div>
      </div>
    </div>
  );
}
