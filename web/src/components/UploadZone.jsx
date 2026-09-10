import React, { useState, useRef } from 'react';
import Icon from './ui/icons';
import SectionHeader from './ui/SectionHeader';

const SUPPORTED_EXTS = ['.wav', '.iq', '.bin', '.raw', '.sigmf-data', '.dat'];

export default function UploadZone({ onAnalyze, isAnalyzing }) {
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fsHint, setFsHint] = useState('200000');
  const [modHint, setModHint] = useState('');
  const [uploadError, setUploadError] = useState(null);

  const fileInputRef = useRef(null);

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragOver(true);
    } else if (e.type === 'dragleave') {
      setDragOver(false);
    }
  };

  const validateFile = (file) => {
    if (!file) return false;
    const name = file.name.toLowerCase();
    const isSupported = SUPPORTED_EXTS.some(ext => name.endsWith(ext));
    if (!isSupported) {
      setUploadError(`Unsupported format '${name}'. Supported: ${SUPPORTED_EXTS.join(', ')}`);
      return false;
    }
    setUploadError(null);
    return true;
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (validateFile(file)) {
        setSelectedFile(file);
      }
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (validateFile(file)) {
        setSelectedFile(file);
      }
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!selectedFile) {
      setUploadError('Please select or drop a signal file first.');
      return;
    }
    setUploadError(null);
    onAnalyze(selectedFile, fsHint ? parseFloat(fsHint) : null, modHint || null);
  };

  const formatBytes = (bytes) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const openFilePicker = () => fileInputRef.current?.click();

  const dropzoneBorder = dragOver
    ? 'var(--accent)'
    : selectedFile
      ? 'var(--ok-border)'
      : 'var(--border-strong)';

  return (
    <section className="panel panel--ticks panel--pad" style={{ marginBottom: 'var(--sp-5)' }}>
      <SectionHeader
        icon="upload"
        title="Signal Ingest"
        caption="Upload raw IQ or RF waveform recordings to trigger the autonomous S0→S6 pipeline."
      >
        <span className="metric-pill">
          <span className="mp-label">Max Upload</span>
          <span className="mp-value">2 GB</span>
        </span>
      </SectionHeader>

      <form onSubmit={handleSubmit}>
        {/* Drop Zone */}
        <div
          role="button"
          tabIndex={0}
          aria-label="Select or drop an RF signal file"
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={openFilePicker}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              openFilePicker();
            }
          }}
          style={{
            border: `1px dashed ${dropzoneBorder}`,
            borderRadius: 'var(--radius-md)',
            padding: '26px 16px',
            textAlign: 'center',
            background: dragOver
              ? 'var(--accent-dim)'
              : selectedFile
                ? 'var(--ok-dim)'
                : 'var(--surface-inset)',
            cursor: 'pointer',
            transition: 'border-color 0.15s ease, background 0.15s ease',
            marginBottom: 'var(--sp-4)',
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            onChange={handleFileChange}
            accept=".wav,.iq,.bin,.raw,.sigmf-data,.dat"
            style={{ display: 'none' }}
            aria-hidden="true"
            tabIndex={-1}
          />

          <div style={{ color: selectedFile ? 'var(--ok)' : 'var(--text-tertiary)', marginBottom: 8 }}>
            <Icon name={selectedFile ? 'file' : 'upload'} size={22} />
          </div>

          {selectedFile ? (
            <div>
              <div className="t-data" style={{ fontWeight: 600, fontSize: 13 }}>
                {selectedFile.name}
              </div>
              <div style={{ fontSize: 12, color: 'var(--ok)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>
                {formatBytes(selectedFile.size)} · ready for analysis
              </div>
            </div>
          ) : (
            <div>
              <div style={{ fontWeight: 500, color: 'var(--text-primary)', fontSize: 13 }}>
                Drop an RF waveform capture here, or{' '}
                <span style={{ color: 'var(--accent-strong)', textDecoration: 'underline', textUnderlineOffset: 3 }}>
                  browse
                </span>
              </div>
              <div className="t-caption" style={{ marginTop: 4, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                .wav · .iq · .raw · .bin · .sigmf-data · .dat
              </div>
            </div>
          )}
        </div>

        {uploadError && (
          <div
            role="alert"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              background: 'var(--danger-dim)',
              color: 'var(--danger)',
              border: '1px solid var(--danger-border)',
              padding: '9px 12px',
              borderRadius: 'var(--radius-md)',
              fontSize: 12,
              marginBottom: 'var(--sp-4)',
            }}
          >
            <Icon name="alert" size={14} />
            {uploadError}
          </div>
        )}

        {/* Hints and Controls */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: 'var(--sp-3)',
            alignItems: 'end',
          }}
        >
          <div>
            <label className="field-label" htmlFor="fs-hint-input">
              Sample Rate Hint (Fs Hz)
            </label>
            <input
              id="fs-hint-input"
              className="input"
              type="number"
              value={fsHint}
              onChange={(e) => setFsHint(e.target.value)}
              placeholder="e.g. 200000"
            />
          </div>

          <div>
            <label className="field-label" htmlFor="mod-hint-select">
              Modulation Hint (Optional)
            </label>
            <select
              id="mod-hint-select"
              className="select"
              value={modHint}
              onChange={(e) => setModHint(e.target.value)}
            >
              <option value="">Auto-Detect (Blind)</option>
              <option value="bpsk">BPSK</option>
              <option value="qpsk">QPSK</option>
              <option value="8psk">8-PSK</option>
              <option value="16qam">16-QAM</option>
              <option value="2fsk">2-FSK</option>
              <option value="4fsk">4-FSK</option>
            </select>
          </div>

          <button
            type="submit"
            disabled={!selectedFile || isAnalyzing}
            className="btn btn--primary"
            style={{ height: 37 }}
          >
            {isAnalyzing ? (
              <>
                <span className="spin-anim" style={{ display: 'inline-flex' }}>
                  <Icon name="reset" size={13} />
                </span>
                PROCESSING…
              </>
            ) : (
              <>
                <Icon name="play" size={13} />
                RUN PIPELINE
              </>
            )}
          </button>
        </div>
      </form>
    </section>
  );
}
