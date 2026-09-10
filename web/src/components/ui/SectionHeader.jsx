import React from 'react';
import Icon from './icons';

/**
 * Standard panel/section heading: optional icon, uppercase title,
 * caption, and a right-aligned actions slot.
 */
export default function SectionHeader({ icon, title, caption, children, style = {} }) {
  return (
    <div className="panel-header" style={style}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        {icon && (
          <span style={{ color: 'var(--accent)', marginTop: 1 }}>
            <Icon name={icon} size={16} />
          </span>
        )}
        <div>
          <h2 className="t-section">{title}</h2>
          {caption && <p className="t-caption" style={{ marginTop: 2 }}>{caption}</p>}
        </div>
      </div>
      {children && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {children}
        </div>
      )}
    </div>
  );
}
