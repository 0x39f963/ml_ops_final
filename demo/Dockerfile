FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY demo/requirements.txt /tmp/demo-requirements.txt
RUN pip install --no-cache-dir -r /tmp/demo-requirements.txt

COPY demo /app/demo
COPY data/sample_synth.parquet /app/data/sample_synth.parquet

WORKDIR /app/demo

EXPOSE 8501 8502

CMD ["/bin/sh", "/app/demo/entrypoint.sh"]
