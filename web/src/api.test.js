import { test } from 'node:test';
import assert from 'node:assert';

// Mock import.meta.env
globalThis.window = {};

test('getArtifactUrl constructs proper path', async () => {
  const { getArtifactUrl } = await import('./api.js');
  const url = getArtifactUrl('run_test_123', 's1_psd_plot');
  assert.strictEqual(url, '/runs/run_test_123/artifacts/s1_psd_plot');
});

test('getArtifactUrl escapes parameters', async () => {
  const { getArtifactUrl } = await import('./api.js');
  const url = getArtifactUrl('run/with/slash', 'plot#1');
  assert.strictEqual(url, '/runs/run%2Fwith%2Fslash/artifacts/plot%231');
});
