import React, { useState, useRef } from 'react';

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

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: '12px',
      padding: '24px',
      marginBottom: '24px',
      boxShadow: '0 4px 20px rgba(0, 0, 0, 0.25)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <div>
          <h2 style={{ fontSize: '15px', fontWeight: 700, color: '#fff', letterSpacing: '0.3px' }}>
            SIGNAL INGEST & LAUNCHPAD
          </h2>
          <p style={{ fontSize: '13px', color: 'var(--text-dim)' }}>
            Upload raw IQ or RF waveform recordings to trigger the autonomous S0→S6 pipeline.
          </p>
        </div>
        <span style={{
          fontSize: '11px',
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-dim)',
          background: 'var(--bg-main)',
          padding: '4px 8px',
          borderRadius: '4px',
          border: '1px solid var(--border)',
        }}>
          Max: 2 GB
        </span>
      </div>

      <form onSubmit={handleSubmit}>
        {/* Drop Zone */}
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          style={{
            border: `2px dashed ${dragOver ? 'var(--cyan)' : selectedFile ? 'var(--emerald)' : 'var(--border)'}`,
            borderRadius: '8px',
            padding: '28px 16px',
            textAlign: 'center',
            background: dragOver ? 'var(--cyan-glow)' : selectedFile ? 'rgba(16, 185, 129, 0.04)' : 'var(--bg-input)',
            cursor: 'pointer',
            transition: 'all 0.2s ease',
            marginBottom: '16px',
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            onChange={handleFileChange}
            accept=".wav,.iq,.bin,.raw,.sigmf-data,.dat"
            style={{ display: 'none' }}
          />

          <div style={{ fontSize: '32px', marginBottom: '8px' }}>
            {selectedFile ? '📡' : '📁'}
          </div>

          {selectedFile ? (
            <div>
              <div style={{ fontWeight: 700, color: '#fff', fontSize: '14px', fontFamily: 'var(--font-mono)' }}>
                {selectedFile.name}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--emerald)', marginTop: '4px' }}>
                {formatBytes(selectedFile.size)} • Ready for analysis
              </div>
            </div>
          ) : (
            <div>
              <div style={{ fontWeight: 600, color: 'var(--text-main)', fontSize: '14px' }}>
                Drag and drop your RF waveform here, or <span style={{ color: 'var(--cyan)', textDecoration: 'underline' }}>browse</span>
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginTop: '4px' }}>
                Supported: .wav, .iq, .raw, .bin, .sigmf-data
              </div>
            </div>
          )}
        </div>

        {uploadError && (
          <div style={{
            background: 'var(--rose-glow)',
            color: 'var(--rose)',
            border: '1px solid rgba(244, 63, 94, 0.3)',
            padding: '10px 14px',
            borderRadius: '6px',
            fontSize: '12px',
            marginBottom: '16px',
          }}>
            ⚠️ {uploadError}
          </div>
        )}

        {/* Hints and Controls */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr)) auto',
          gap: '12px',
          alignItems: 'end',
        }}>
          <div>
            <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
              SAMPLE RATE HINT (FS HZ)
            </label>
            <input
              type="number"
              value={fsHint}
              onChange={(e) => setFsHint(e.target.value)}
              placeholder="e.g. 200000"
              style={{
                width: '100%',
                background: 'var(--bg-input)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                padding: '8px 12px',
                color: '#fff',
                fontFamily: 'var(--font-mono)',
                fontSize: '13px',
                outline: 'none',
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
              MODULATION HINT (OPTIONAL)
            </label>
            <select
              value={modHint}
              onChange={(e) => setModHint(e.target.value)}
              style={{
                width: '100%',
                background: 'var(--bg-input)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                padding: '8px 12px',
                color: '#fff',
                fontSize: '13px',
                outline: 'none',
                cursor: 'pointer',
              }}
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
            style={{
              background: !selectedFile || isAnalyzing
                ? 'var(--bg-input)'
                : 'linear-gradient(135deg, #06b6d4 0%, #2563eb 100%)',
              color: !selectedFile || isAnalyzing ? 'var(--text-dim)' : '#ffffff',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '8px 24px',
              fontWeight: 700,
              fontSize: '13px',
              cursor: !selectedFile || isAnalyzing ? 'not-allowed' : 'pointer',
              height: '37px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              boxShadow: !selectedFile || isAnalyzing ? 'none' : '0 0 12px rgba(6, 182, 212, 0.3)',
              transition: 'all 0.15s ease',
            }}
          >
            {isAnalyzing ? (
              <>
                <span className="spin-anim" style={{ display: 'inline-block' }}>⟳</span>
                <span>PROCESSING...</span>
              </>
            ) : (
              <>
                <span>🚀</span>
                <span>RUN PIPELINE</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
