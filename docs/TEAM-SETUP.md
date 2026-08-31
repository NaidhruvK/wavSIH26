# Raaya — environment setup

Two phases. **Phase A works right now and needs no repo.** Phase B is for once
Naidhruv posts the clone URL.

Target: **Python 3.11** (a fresh install gives 3.11.9). If you already have any
3.11.x you are fine — do not reinstall. The container is pinned to
`python:3.11.9-slim`.

---

# Phase A — do this tonight, no repo needed

## A1. Install Python 3.11

**Windows** — one command in PowerShell or Terminal:

```powershell
winget install --id Python.Python.3.11 -e
```

No winget? Installer:
<https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe>
Tick **"Add python.exe to PATH"** during setup.

**macOS:** `brew install python@3.11`
**Linux (Debian/Ubuntu):** `sudo apt install python3.11 python3.11-venv`

## A2. Check it

```powershell
py -3.11 --version          # Windows
python3.11 --version        # macOS / Linux
```

Expected `Python 3.11.9`, or any other 3.11.x — both fine.

## A3. Build a throwaway environment and install the stack

Do this anywhere — a scratch folder, not your project folder. It is only to
prove the libraries install and work on your machine. Delete it afterwards if
you like.

```powershell
mkdir raaya-precheck
cd raaya-precheck
py -3.11 -m venv .venv
.venv\Scripts\activate
```

macOS/Linux: `python3.11 -m venv .venv && source .venv/bin/activate`

Then, with the environment active:

```
pip install numpy==2.4.6 scipy==1.17.1 matplotlib==3.11.1 galois==0.4.11 soundfile==0.14.0 SigMF==1.13.0 scikit-commpy==0.8.0 reedsolo==1.7.0 scikit-learn==1.9.0 lightgbm==4.7.0 fastapi==0.141.1 pydantic==2.13.5 pytest==9.1.1
```

Takes a few minutes — galois pulls numba and llvmlite, which are large.

## A4. Prove it actually works

Save `stack_check.py` (sent alongside this file) into `raaya-precheck` and run:

```powershell
python stack_check.py
```

Expected: **11/11 passed**.

It exercises the libraries rather than importing them — a GF(2) rank through
galois, a Viterbi round-trip hard *and* soft, a Reed–Solomon correction, a
LightGBM fit. Thirty seconds.

**If anything says FAIL, post the whole output before doing anything else.** A
broken environment found tonight is free. Found on 6 September it costs a gate.

---

# Phase B — once Naidhruv posts the repo URL

```powershell
git clone <URL>
cd raaya
git config user.name  "Your Name"
git config user.email "you@example.com"
git checkout -b yourname/your-feature      # never work on main

py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python docs/stack_check.py                 # 11/11 again, now from the repo
```

Branch names are `<yourname>/<feature>` — `dheeraj/zoo-v0`, `anvith/s3-gardner`,
`nehal/s4-rank`, `naidhruv/orchestrator`. One branch per person per feature.

You can then delete the `raaya-precheck` folder from Phase A.

---

## Two things that will bite whoever writes the Dockerfile

**`python:*-slim` has no `libgomp1`, and LightGBM needs it.** Without it the
classifier imports fine and dies the first time it trains — inside the
container, which nobody looks at until the clean rebuild on 6 Sep.

```dockerfile
FROM python:3.11.9-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

**Never copy pinned versions between Python versions.** `numpy 2.5.x` and
`scipy 1.18.x` declare `Requires-Python >=3.12` — not "resolve differently",
*not installable* on 3.11. Our `requirements.txt` briefly had exactly those,
carried over from a 3.13 machine, and would have failed the image build
outright.

Full evidence and reasoning: `docs/python-version-decision.md`.
