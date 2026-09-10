import React from 'react';

/**
 * Minimal stroke icon set (16×16 grid, 1.5px stroke).
 * Replaces emoji glyphs with consistent instrument-style iconography.
 */

const PATHS = {
  // Signal / antenna: transmission mast with waves
  antenna: (
    <>
      <path d="M8 6.5v7" />
      <circle cx="8" cy="5" r="1.5" />
      <path d="M4.5 2.5a6 6 0 0 0 0 5M11.5 2.5a6 6 0 0 1 0 5" />
    </>
  ),
  // Upload: tray with arrow
  upload: (
    <>
      <path d="M8 10V2.5M4.8 5.2 8 2l3.2 3.2" />
      <path d="M2.5 10.5v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2" />
    </>
  ),
  // File / capture
  file: (
    <>
      <path d="M4 1.5h5l3 3v10h-8z" />
      <path d="M9 1.5v3h3" />
    </>
  ),
  // Waveform
  waveform: (
    <path d="M1.5 8h2l1.5-4 2 8 2-8 1.5 4h2" />
  ),
  // Spectrum bars
  spectrum: (
    <path d="M2.5 13.5v-3M5.5 13.5v-6M8.5 13.5V2.5M11.5 13.5v-5M14 13.5v-8" />
  ),
  // Crosshair / constellation
  crosshair: (
    <>
      <circle cx="8" cy="8" r="5" />
      <path d="M8 1v3M8 12v3M1 8h3M12 8h3" />
    </>
  ),
  // Heatmap / waterfall layers
  layers: (
    <path d="M2 4.5h12M2 8h12M2 11.5h12" />
  ),
  // Bar chart (rank / hypotheses)
  barChart: (
    <>
      <path d="M2 13.5h12" />
      <path d="M4 13.5V8M8 13.5V4M12 13.5v-3.5" />
    </>
  ),
  // Trend line (envelope curves)
  trend: (
    <path d="M1.5 12.5 6 8l3 3 5.5-6.5" />
  ),
  // Boundary / envelope frame
  boundary: (
    <>
      <rect x="2" y="2" width="12" height="12" />
      <path d="M5 11 11 5" />
    </>
  ),
  // Scale / ranking
  scale: (
    <>
      <path d="M8 2.5v11M3.5 13.5h9" />
      <path d="M3.5 5 8 3.5 12.5 5" />
      <path d="M2 9a1.8 1.8 0 0 0 3 0L3.5 5.2zM11 9a1.8 1.8 0 0 0 3 0L12.5 5.2z" />
    </>
  ),
  // Plug / registry
  plug: (
    <>
      <path d="M5.5 2v3M10.5 2v3" />
      <path d="M4 5h8v3a4 4 0 0 1-8 0z" />
      <path d="M8 12v2.5" />
    </>
  ),
  // Copy
  copy: (
    <>
      <rect x="5.5" y="5.5" width="8" height="8" rx="1" />
      <path d="M10.5 3.5v-1a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h1" />
    </>
  ),
  // Close
  x: (
    <path d="M4 4l8 8M12 4l-8 8" />
  ),
  // Check
  check: (
    <path d="M3 8.5 6.5 12 13 4.5" />
  ),
  // Alert triangle
  alert: (
    <>
      <path d="M8 2 14.5 13.5h-13z" />
      <path d="M8 6.5v3.2M8 11.6v.4" />
    </>
  ),
  // Payload / document text
  doc: (
    <>
      <path d="M4 1.5h5l3 3v10h-8z" />
      <path d="M9 1.5v3h3M6 8h4M6 10.5h4" />
    </>
  ),
  // Play (run pipeline)
  play: (
    <path d="M5 3.5v9l7.5-4.5z" />
  ),
  // External link
  external: (
    <>
      <path d="M6.5 3.5h-3a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-3" />
      <path d="M9.5 2.5h4v4M13.5 2.5 7.5 8.5" />
    </>
  ),
  // Reset / new analysis
  reset: (
    <>
      <path d="M13.5 8a5.5 5.5 0 1 1-1.8-4.1" />
      <path d="M13.5 2.5v2.8h-2.8" />
    </>
  ),
};

export default function Icon({ name, size = 15, className = '', style = {}, title }) {
  const path = PATHS[name];
  if (!path) return null;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={style}
      role={title ? 'img' : 'presentation'}
      aria-hidden={title ? undefined : true}
    >
      {title && <title>{title}</title>}
      {path}
    </svg>
  );
}
