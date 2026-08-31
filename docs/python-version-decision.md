# Python version — measured, not argued

**Nehal · 30 August 2026 · decided, please install**

---

## The decision: **Python 3.11.9**, everywhere

```
Windows / macOS   winget install --id Python.Python.3.11      # gives 3.11.9
container         FROM python:3.11.9-slim
```

One command. Everyone run it, including if you already have some other 3.11 —
it costs a minute and removes a variable.

Already done and verified on Nehal's machine: `.venv` is now 3.11.9,
`docs/stack_check.py` passes **11/11**, `tests/unit` passes **83/83**, and the
S4 reports regenerate byte-identically to the ones produced on 3.13.

## Why 3.11 at all

Everything works on everything, so this is a coin-toss on technical merit:

| Environment | Result | numpy | scipy |
|---|---|---|---|
| 3.10.6, Windows local | **11/11** | 2.2.6 | 1.15.3 |
| **3.11.9, Windows local** | **11/11** | 2.4.6 | 1.17.1 |
| 3.11.9, `python:3.11.9-slim` | **11/11** | 2.4.6 | 1.17.1 |
| 3.11.16, `python:3.11-slim` | **11/11** | 2.4.6 | 1.17.1 |
| 3.13.15, `python:3.13-slim` | **11/11** | 2.5.2 | 1.18.1 |

Not imports — exercised: `galois` computes a GF(2) rank, `commpy` round-trips a
Viterbi decode hard **and** soft, `reedsolo` corrects five symbol errors,
LightGBM trains a model.

When evidence does not prefer either option, take the one already written down
in the Command Center and stop spending attention on it. 3.11 also carries less
forward risk: this architecture runs to the December finale, and dependencies
added in October are likelier to be missing wheels on the newest Python.

## Why 3.11.**9** specifically, and not "the latest 3.11"

Python 3.11 is in security-only mode, and security-only releases are
**source-only** — python.org publishes no Windows installer past 3.11.9.
`winget` confirms it:

```
Name        Id                 Version
Python 3.11 Python.Python.3.11 3.11.9
```

So 3.11.9 is the newest 3.11 the whole team can install with a single command
and no compiler. Pinning the image to `python:3.11.9-slim` then makes the
container the *same interpreter* the four of us develop on, which is strictly
better than being one patch newer in one place and not the other.

The trade, stated plainly: 3.11.9 is from April 2024 and misses subsequent
CPython security fixes. For an offline single-analyst tool with no auth, no
network and no untrusted deserialisation, that is an acceptable trade — and it
is a deliberate one, not an oversight. If anyone objects, the alternative is
`uv python install 3.11`, which ships newer standalone 3.11 builds on Windows,
at the cost of everyone installing `uv` first.

**Patch version does not affect compatibility.** Every compiled wheel is tagged
`cp311-cp311` — there is no patch component:

```
numpy-2.4.6-cp311-cp311-manylinux...whl      scipy-1.17.1-cp311-cp311-...whl
numba-0.67.0-cp311-cp311-...whl              llvmlite-0.49.0-cp311-cp311-...whl
galois-0.4.11-py3-none-any.whl               lightgbm-4.7.0-py3-none-manylinux...whl
```

3.11.9 and 3.11.16 resolve to identical package versions and both score 11/11.
We pin 3.11.9 for *uniformity*, not compatibility.

## Three findings that matter more than the version

**1. Pins copied from a 3.13 environment do not install on 3.11 at all.**
An earlier `requirements.txt` here pinned `numpy==2.5.2` and `scipy==1.18.1`,
taken from the 3.13 box S4 was first built on. Both are hard-incompatible:

```
numpy 2.5.0, 2.5.1, 2.5.2   Requires-Python >=3.12
scipy 1.18.0, 1.18.1        Requires-Python >=3.12
```

Not "resolves differently" — *not installable*. That file would have failed the
image build outright. `requirements.txt` is now pinned from an actual 3.11.9
resolution and verified by installing it from scratch into an empty venv.

**2. `python:*-slim` has no `libgomp1`, and LightGBM needs it.** The only
failure in the whole exercise, identical on 3.11 and 3.13:

```
FAIL lightgbm: trains    OSError: libgomp.so.1: cannot open shared object file
```

Without it the classifier imports fine and dies the first time it trains —
inside the container, which nobody looks at until the 6 Sep clean rebuild.

**3. `python:3.11-slim` is a moving tag.** Between the two images tested today
the base OS moved underneath: `3.11.9-slim` is glibc 2.36, `3.11-slim` is
glibc 2.41. It changed nothing here, but the 8 Sep gate requires regenerating
the envelope numbers from a clean checkout and getting *identical* results.
Pin the patch.

## Dockerfile base — for Naidhruv

```dockerfile
FROM python:3.11.9-slim        # pinned patch, and the same one we all run locally

# libgomp1:    OpenMP runtime, required by LightGBM. Not present in -slim.
# libsndfile1: the C library behind soundfile's WAV I/O.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

`libsndfile1` is pre-emptive — `soundfile` imported fine in the probe, but it
wraps a system library and the wheel does not always carry it. Dheeraj should
confirm an actual WAV *read* inside the container before we rely on it.

## Reproduce any of this

```bash
python docs/stack_check.py                      # local

docker run --rm -v "$PWD:/w" -w /w python:3.11.9-slim bash -c \
  "apt-get update -qq && apt-get install -y -qq libgomp1 && \
   pip install -q -r requirements.txt && python docs/stack_check.py"
```

`stack_check.py` runs in ~30 s and is worth running inside the image on 6 Sep
and again on 9 Sep. It is what turns "the container built" into "the container
works".
