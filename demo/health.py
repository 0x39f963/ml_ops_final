"""Health endpoint for the demo frontend container."""

from __future__ import annotations

from fastapi import FastAPI


app = FastAPI(title="NBO demo health", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "nbo-demo"}
