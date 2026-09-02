# Raaya - base image.
#
# OWNERSHIP: Docker is Naidhruv's. This is written by Nehal on 31 Aug as a
# tested starting point, not a claim on the file - change or replace anything.
# What is worth keeping is the two apt packages and the pinned tag, because
# each one cost real time to find:
#
#   libgomp1     OpenMP runtime. NOT in python:*-slim. Without it LightGBM
#                imports fine and dies the first time it TRAINS - inside the
#                container, which nobody looks at until the 6 Sep clean
#                rebuild. Measured on both 3.11 and 3.13; nothing to do with
#                the Python version.
#   libsndfile1  the C library behind soundfile's WAV I/O. Pre-emptive - the
#                wheel imports without it, but does not always read a file.
#                Dheeraj should confirm an actual WAV read in the container.
#
# The tag is pinned to the PATCH. `python:3.11-slim` is a moving tag: between
# two pulls on 30 Aug the base moved from glibc 2.36 to 2.41 underneath us. The
# 8 Sep gate is "regenerate from a clean checkout, numbers identical", and that
# cannot mean anything if the floor moves.
#
# 3.11.9 is also exactly what the four of us run locally - it is the newest
# 3.11 with a Windows installer. See docs/python-version-decision.md.

FROM python:3.11.9-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies before source, so a code change does not re-resolve the whole
# stack. numba and llvmlite are large; this layer is the slow one.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Runs something useful today rather than nothing: blind recovery on a
# generated stream, printed to the terminal. Naidhruv - swap this for
# `uvicorn service.main:app --host 0.0.0.0 --port 8000` when service/ lands.
CMD ["python", "-m", "pipeline.s4_recover.cli", "--demo"]
