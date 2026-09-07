# Raaya - multi-stage production image.
#
# OWNERSHIP: Docker is Naidhruv's.
# Incorporates Nehal's pinned Python 3.11.9-slim base and essential apt packages:
#   libgomp1     OpenMP runtime for LightGBM.
#   libsndfile1  C library behind soundfile's WAV I/O.
#
# Stage 1 builds the Vite/React frontend Command Center.
# Stage 2 sets up the Python backend service and mounts the built frontend.

# Stage 1: Frontend Build
FROM node:20-alpine AS frontend-builder
WORKDIR /app/web

# Install npm dependencies first for layer caching
COPY web/package*.json ./
RUN npm install

# Build production UI bundle
COPY web/ ./
RUN npm run build

# Stage 2: Python Runtime Environment
FROM python:3.11.9-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies before source for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy repository source code
COPY . .

# Copy compiled frontend assets from Stage 1 into web/dist
COPY --from=frontend-builder /app/web/dist /app/web/dist

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]

