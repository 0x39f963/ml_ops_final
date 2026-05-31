# Generated at: 2026-05-31 21:53:25 MSK
"""Thin MLflow logging hook for training runs."""

from __future__ import annotations

import os
from typing import Any


def log_run(
    params: dict[str, Any],
    metrics: dict[str, Any],
    artifacts: dict[str, str] | None = None,
) -> str | None:
    """Log params and metrics to MLflow when tracking is configured."""
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    if not tracking_uri:
        print("MLflow logging skipped: MLFLOW_TRACKING_URI is empty.")
        return None

    try:
        import mlflow
    except ImportError:
        print("MLflow logging skipped: mlflow is not installed.")
        return None

    mlflow.set_tracking_uri(tracking_uri)
    run_name = str(params.get("run_id", "nbo_train"))
    with mlflow.start_run(run_name=run_name) as run:
        safe_params = {key: _safe_value(value) for key, value in params.items()}
        mlflow.log_params(safe_params)
        safe_metrics = {
            key: float(value)
            for key, value in metrics.items()
            if isinstance(value, (int, float)) and value is not None
        }
        if safe_metrics:
            mlflow.log_metrics(safe_metrics)
        if artifacts:
            print("MLflow artifact logging is deferred to b05.")
        return run.info.run_id


def _safe_value(value: Any) -> str | int | float | bool:
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
