# Generated at: 2026-06-01 07:30:04 MSK

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY artifacts /app/artifacts
COPY data/sample_synth.parquet /app/data/sample_synth.parquet

EXPOSE 8000

