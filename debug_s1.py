from pipeline.s0_ingest import ingest
from pipeline.s1_detect import detect
import json
from pathlib import Path

for f in sorted(Path('zoo/corpus/rf').glob('*dB_*.wav')):
    truth = json.loads(f.with_suffix('.json').read_text())
    r = ingest(f)
    d = detect(r.iq, r.fs)
    print(f'{f.name:30s} truth={truth["snr_db"]:6.1f}dB  measured={d.snr_db:6.1f}dB  diff={d.snr_db-truth["snr_db"]:+.1f}dB')