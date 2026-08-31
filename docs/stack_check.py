"""Does the whole Raaya stack resolve, import and work on this Python?

Run inside a container to settle the 3.11-vs-3.13 question with evidence:

    docker run --rm -v "$PWD:/w" -w /w python:3.11-slim \
        bash -c "pip install -q -r docs/stack_probe.txt && python docs/stack_check.py"

Checks more than imports. An import that succeeds and a function that returns
the wrong answer are very different things, and the second one is what actually
loses a demo - so the FEC libraries get exercised, not just loaded.
"""

from __future__ import annotations

import platform
import sys
import traceback

RESULTS: list[tuple[str, bool, str]] = []


def check(name):
    def wrap(fn):
        try:
            detail = fn() or ""
            RESULTS.append((name, True, str(detail)))
        except Exception as exc:
            RESULTS.append((name, False, "%s: %s" % (type(exc).__name__, exc)))
            if "-v" in sys.argv:
                traceback.print_exc()
        return fn
    return wrap


@check("numpy")
def _numpy():
    import numpy
    return numpy.__version__


@check("scipy")
def _scipy():
    import scipy
    return scipy.__version__


@check("galois: rank over GF(2)")
def _galois():
    import galois, numpy as np
    gf2 = galois.GF(2)
    rng = np.random.default_rng(0)
    A = rng.integers(0, 2, (30, 7), dtype=np.uint8)
    B = rng.integers(0, 2, (7, 20), dtype=np.uint8)
    M = (A @ B) % 2
    r = int(np.linalg.matrix_rank(gf2(M)))
    assert r == 7, "expected rank 7, got %d" % r
    return "%s (rank ok)" % galois.__version__


@check("commpy: Viterbi round-trip, hard AND soft")
def _commpy():
    import numpy as np
    from commpy.channelcoding import Trellis, conv_encode, viterbi_decode
    t = Trellis(np.array([6]), np.array([[0o171, 0o133]]))
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 1000).astype(int)
    enc = np.asarray(conv_encode(bits, t))
    hard = viterbi_decode(enc, t, tb_depth=35, decoding_type="hard")
    assert np.array_equal(hard[:len(bits)], bits), "hard decode wrong"
    soft = viterbi_decode(2.0 * enc - 1.0, t, tb_depth=35, decoding_type="unquantized")
    assert np.array_equal(soft[:len(bits)], bits), "soft decode wrong"
    import commpy
    return "%s (hard+soft exact)" % getattr(commpy, "__version__", "?")


@check("reedsolo: encode/correct")
def _reedsolo():
    import reedsolo
    rs = reedsolo.RSCodec(32)
    payload = bytes(range(64))
    enc = bytearray(rs.encode(payload))
    for i in (0, 5, 17, 40, 70):
        enc[i] ^= 0xFF
    assert bytes(rs.decode(bytes(enc))[0]) == payload
    return "corrects 5 symbol errors"


@check("lightgbm: trains")
def _lightgbm():
    import lightgbm as lgb, numpy as np
    rng = np.random.default_rng(0)
    X = rng.normal(size=(400, 6)); y = (X[:, 0] + X[:, 1] > 0).astype(int)
    m = lgb.LGBMClassifier(n_estimators=20, verbose=-1).fit(X, y)
    acc = (m.predict(X) == y).mean()
    assert acc > 0.8, "accuracy %.2f" % acc
    return "%s (train ok)" % lgb.__version__


@check("scikit-learn")
def _sklearn():
    import sklearn
    return sklearn.__version__


@check("fastapi + pydantic")
def _fastapi():
    import fastapi, pydantic
    from pydantic import BaseModel

    class R(BaseModel):
        stage: int
        status: str
    assert R(stage=4, status="ok").stage == 4
    return "fastapi %s / pydantic %s" % (fastapi.__version__, pydantic.VERSION)


@check("soundfile (libsndfile)")
def _soundfile():
    import soundfile
    return soundfile.__version__


@check("sigmf")
def _sigmf():
    import sigmf
    return getattr(sigmf, "__version__", "ok")


@check("matplotlib (Agg)")
def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(); ax.plot([0, 1], [0, 1]); plt.close(fig)
    return matplotlib.__version__


if __name__ == "__main__":
    print("=" * 68)
    print("Python %s  (%s)" % (platform.python_version(), platform.platform()))
    print("=" * 68)
    ok = 0
    for name, passed, detail in RESULTS:
        print("  %-4s %-38s %s" % ("PASS" if passed else "FAIL", name, detail))
        ok += passed
    print("-" * 68)
    print("  %d/%d passed" % (ok, len(RESULTS)))
    sys.exit(0 if ok == len(RESULTS) else 1)
