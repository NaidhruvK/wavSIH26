/**
 * API communication module for Raaya / wavSIH26 FastAPI backend.
 * 
 * Supports both direct backend origin (http://127.0.0.1:8000) and Vite proxy.
 */

const API_BASE = (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_URL) || '';

/**
 * Upload a .wav, .iq, or supported raw RF file to initiate background S0->S6 analysis.
 * 
 * @param {File} file
 * @param {number|null} fsHint - Optional sample rate hint in Hz
 * @param {string|null} modSchemeHint - Optional modulation scheme hint
 * @returns {Promise<{run_id: string, status: string, message: string, filename: string}>}
 */
export async function uploadAndAnalyze(file, fsHint = null, modSchemeHint = null) {
  const formData = new FormData();
  formData.append('file', file);
  if (fsHint !== null && fsHint !== undefined && fsHint !== '') {
    formData.append('fs_hint', String(fsHint));
  }
  if (modSchemeHint && modSchemeHint.trim() !== '') {
    formData.append('mod_scheme_hint', modSchemeHint.trim().toLowerCase());
  }

  const response = await fetch(`${API_BASE}/analyze`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    let errorDetail = `Upload failed with status ${response.status}`;
    try {
      const err = await response.json();
      if (err.detail) errorDetail = err.detail;
    } catch {
      // Use fallback error
    }
    throw new Error(errorDetail);
  }

  return response.json();
}

/**
 * Fetch the complete AnalysisReport for a given run.
 * 
 * @param {string} runId
 * @returns {Promise<Object>}
 */
export async function getRunReport(runId) {
  const response = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}`);
  if (!response.ok) {
    let errorDetail = `Failed to fetch run '${runId}' (status ${response.status})`;
    try {
      const err = await response.json();
      if (err.detail) errorDetail = err.detail;
    } catch {
      // Use fallback error
    }
    throw new Error(errorDetail);
  }
  return response.json();
}

/**
 * Fetch a specific stage execution result (by index 0-6 or stage name).
 * 
 * @param {string} runId
 * @param {number|string} stageNum
 * @returns {Promise<Object>}
 */
export async function getStageResult(runId, stageNum) {
  const response = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}/stage/${encodeURIComponent(stageNum)}`);
  if (!response.ok) {
    let errorDetail = `Failed to fetch stage '${stageNum}' for run '${runId}'`;
    try {
      const err = await response.json();
      if (err.detail) errorDetail = err.detail;
    } catch {
      // Use fallback error
    }
    throw new Error(errorDetail);
  }
  return response.json();
}

/**
 * Get URL to retrieve a plot or matrix artifact file.
 * 
 * @param {string} runId
 * @param {string} artifactName
 * @returns {string}
 */
export function getArtifactUrl(runId, artifactName) {
  return `${API_BASE}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactName)}`;
}

/**
 * Fetch an artifact's JSON data directly.
 * 
 * @param {string} runId
 * @param {string} artifactName
 * @returns {Promise<Object>}
 */
export async function getArtifact(runId, artifactName) {
  const url = getArtifactUrl(runId, artifactName);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load artifact '${artifactName}' (${response.status})`);
  }
  return response.json();
}

/**
 * Check backend service health.
 * 
 * @returns {Promise<{status: string, service: string, version: string, timestamp: string}>}
 */
export async function getHealth() {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }
  return response.json();
}

/**
 * Fetch plugin registry introspection data.
 * 
 * @returns {Promise<{counts: Object, modulations: Array, interleavers: Array, codes: Array}>}
 */
export async function getRegistry() {
  const response = await fetch(`${API_BASE}/registry`);
  if (!response.ok) {
    throw new Error(`Registry check failed with status ${response.status}`);
  }
  return response.json();
}

/**
 * Fetch operating envelope specifications and bounds.
 * 
 * @returns {Promise<Object>}
 */
export async function getEnvelope() {
  const response = await fetch(`${API_BASE}/envelope`);
  if (!response.ok) {
    throw new Error(`Envelope check failed with status ${response.status}`);
  }
  return response.json();
}
