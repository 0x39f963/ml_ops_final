"""MLflow tracking and registry helpers for NBO champion/challenger aliases."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
from typing import Any


TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI") or "file:./mlruns"
MODEL_NAME = os.environ.get("MLFLOW_MODEL_NAME", "nbo_topn")
CHAMPION_ALIAS = "champion"
CHALLENGER_ALIAS = "challenger"
PREVIOUS_CHAMPION_TAG = "previous_champion_version"
FEATURE_LIST_HASH_TAG = "feature_list_hash"
MODEL_ROLE_TAG = "model_role"
DEFAULT_EXPERIMENT_NAME = os.environ.get("MLFLOW_EXPERIMENT_NAME", MODEL_NAME)

LOGGER = logging.getLogger(__name__)
_METRIC_KEY_RE = re.compile(r"[^A-Za-z0-9_.\-/]")


def log_run(
    params: dict[str, Any],
    metrics: dict[str, Any],
    model: Any | None = None,
    feature_list_hash: str | None = None,
    model_role: str | None = None,
    artifact_path: str = "model",
    run_name: str | None = None,
) -> str | None:
    """Log one training/evaluation run to MLflow and return its run_id.

    model, feature_list_hash, and model_role are optional to keep the current
    b03 call path working until train.py passes the full b05 contract.
    """
    tracking_uri = _tracking_uri()
    if not tracking_uri:
        LOGGER.info("MLflow logging skipped because MLFLOW_TRACKING_URI is empty.")
        return None

    mlflow, _, _ = _mlflow_modules()
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(DEFAULT_EXPERIMENT_NAME)

    safe_params = _safe_params(params)
    safe_metrics = _flat_metrics(metrics)
    feature_hash = feature_list_hash or _string_or_none(params.get(FEATURE_LIST_HASH_TAG))
    role = _role_or_none(model_role)

    with mlflow.start_run(run_name=run_name or str(params.get("run_id", "nbo_train"))) as run:
        if safe_params:
            mlflow.log_params(safe_params)
        if feature_hash:
            mlflow.log_param(FEATURE_LIST_HASH_TAG, feature_hash)
            mlflow.set_tag(FEATURE_LIST_HASH_TAG, feature_hash)
        if role:
            mlflow.set_tag(MODEL_ROLE_TAG, role)
        if safe_metrics:
            mlflow.log_metrics(safe_metrics)
        if model is not None:
            import mlflow.sklearn

            mlflow.sklearn.log_model(sk_model=model, artifact_path=artifact_path)
            mlflow.set_tag("model_artifact_path", artifact_path)
        else:
            model_path = _string_or_none(params.get("model_path"))
            if model_path:
                pointer = {
                    "model_path": model_path,
                    "mode": "local_model_path",
                    "note": "Model bytes stay in gitignored MODEL_DIR; registry stores metadata only.",
                }
                mlflow.log_text(
                    json.dumps(pointer, ensure_ascii=True, indent=2) + "\n",
                    f"{artifact_path}/model_pointer.json",
                )
                mlflow.set_tag("model_path", model_path)
                mlflow.set_tag("model_artifact_path", artifact_path)
                mlflow.set_tag("model_artifact_mode", "local_model_path")
            mlflow.set_tag("model_artifact_logged", "false")
        return run.info.run_id


def register_model_version(
    run_id: str,
    artifact_path: str = "model",
    model_name: str = MODEL_NAME,
    tags: dict[str, Any] | None = None,
    source_uri: str | None = None,
) -> str:
    """Register a run artifact as a model version and return the version id.

    The function is idempotent for the same model_name and run_id.
    source_uri is kept for local file-store tests. For the MLflow server path,
    prefer a run artifact pointer and leave source_uri empty.
    """
    if not run_id:
        raise ValueError("run_id must be non-empty.")

    mlflow, client, _ = _client()
    existing = _version_for_run(client, model_name, run_id)
    if existing is not None:
        _set_version_tags(client, model_name, existing.version, tags)
        return str(existing.version)

    if source_uri:
        _ensure_registered_model(client, model_name)
        version = client.create_model_version(
            name=model_name,
            source=source_uri,
            run_id=run_id,
        )
    else:
        model_uri = f"runs:/{run_id}/{artifact_path}"
        version = mlflow.register_model(model_uri=model_uri, name=model_name)
    version_id = str(version.version)
    _set_version_tags(client, model_name, version_id, tags)
    client.set_model_version_tag(model_name, version_id, "source_run_id", run_id)
    return version_id


def set_alias(alias: str, version: str, model_name: str = MODEL_NAME) -> None:
    """Set a registered model alias to a concrete version."""
    alias = _validate_alias(alias)
    _, client, _ = _client()
    client.set_registered_model_alias(model_name, alias, str(version))


def promote(version: str, model_name: str = MODEL_NAME) -> dict[str, str | None]:
    """Promote version to champion.

    Call this only after the metric gate has passed. The gate is owned by b07.
    """
    version = str(version)
    _, client, _ = _client()
    current = _alias_model_version(client, model_name, CHAMPION_ALIAS)
    previous = str(current.version) if current is not None else None

    if previous and previous != version:
        client.set_model_version_tag(model_name, version, PREVIOUS_CHAMPION_TAG, previous)
    client.set_registered_model_alias(model_name, CHAMPION_ALIAS, version)
    return {"model": model_name, "champion": version, "previous": previous}


def rollback(model_name: str = MODEL_NAME) -> dict[str, str | None]:
    """Restore champion alias to the previous model version."""
    _, client, _ = _client()
    current = _alias_model_version(client, model_name, CHAMPION_ALIAS)
    if current is None:
        raise RuntimeError(f"Cannot rollback {model_name}: champion alias is not set.")

    current_version = str(current.version)
    previous = _string_or_none(current.tags.get(PREVIOUS_CHAMPION_TAG))
    if not previous:
        previous = _previous_numeric_version(client, model_name, current_version)
    if not previous or previous == current_version:
        raise RuntimeError(
            f"Cannot rollback {model_name}: previous champion version is unknown."
        )

    client.set_registered_model_alias(model_name, CHAMPION_ALIAS, previous)
    client.set_model_version_tag(model_name, current_version, "rolled_back_to_version", previous)
    return {
        "model": model_name,
        "champion": previous,
        "rolled_back_from": current_version,
    }


def get_champion(model_name: str = MODEL_NAME) -> dict[str, Any]:
    """Return model info for the champion alias without hardcoded versions."""
    return _get_alias_info(model_name, CHAMPION_ALIAS)


def get_challenger(model_name: str = MODEL_NAME) -> dict[str, Any]:
    """Return model info for the challenger alias without hardcoded versions."""
    return _get_alias_info(model_name, CHALLENGER_ALIAS)


def get_model_info(model_name: str = MODEL_NAME) -> dict[str, Any]:
    """Return compact model info for the b06 /model-info endpoint."""
    champion = get_champion(model_name)
    challenger = get_challenger(model_name)
    return {
        "model": model_name,
        "champion_version": champion["version"],
        "challenger_version": challenger["version"],
        "feature_list_hash": champion["feature_list_hash"],
        "metrics": champion["metrics"],
        "data_cutoff": champion.get("data_cutoff"),
        "champion": champion,
        "challenger": challenger,
    }


def _client():
    mlflow, MlflowClient, MlflowException = _mlflow_modules()
    mlflow.set_tracking_uri(_tracking_uri())
    return mlflow, MlflowClient(tracking_uri=_tracking_uri()), MlflowException


def _mlflow_modules():
    try:
        import mlflow
        from mlflow.exceptions import MlflowException
        from mlflow.tracking import MlflowClient
    except ImportError as exc:
        raise RuntimeError(
            "mlflow is not installed; run `pip install -r requirements.txt`."
        ) from exc
    return mlflow, MlflowClient, MlflowException


def _tracking_uri() -> str:
    value = os.environ.get("MLFLOW_TRACKING_URI")
    if value is None:
        return TRACKING_URI
    return value.strip()


def _validate_alias(alias: str) -> str:
    alias = str(alias)
    if alias not in {CHAMPION_ALIAS, CHALLENGER_ALIAS}:
        raise ValueError("alias must be 'champion' or 'challenger'.")
    return alias


def _role_or_none(model_role: str | None) -> str | None:
    if model_role is None:
        return None
    return _validate_alias(model_role)


def _safe_params(params: dict[str, Any]) -> dict[str, str | int | float | bool]:
    out: dict[str, str | int | float | bool] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            out[str(key)] = value
        else:
            out[str(key)] = json.dumps(value, ensure_ascii=True, sort_keys=True)[:500]
    return out


def _flat_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            number = float(value)
            if math.isfinite(number):
                out[_metric_key(prefix)] = number
            return
        if isinstance(value, dict):
            for key, item in value.items():
                walk(f"{prefix}.{key}" if prefix else str(key), item)

    walk("", metrics)
    return out


def _metric_key(value: str) -> str:
    key = _METRIC_KEY_RE.sub("_", value).strip("._-/")
    return key[:250] or "metric"


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _version_for_run(client: Any, model_name: str, run_id: str) -> Any | None:
    versions = _search_versions(client, model_name)
    matches = [item for item in versions if getattr(item, "run_id", None) == run_id]
    if not matches:
        return None
    return sorted(matches, key=lambda item: int(item.version))[0]


def _search_versions(client: Any, model_name: str) -> list[Any]:
    try:
        return list(client.search_model_versions(f"name = '{model_name}'"))
    except Exception:
        return []


def _ensure_registered_model(client: Any, model_name: str) -> None:
    try:
        client.get_registered_model(model_name)
    except Exception:
        client.create_registered_model(model_name)


def _set_version_tags(
    client: Any,
    model_name: str,
    version: str,
    tags: dict[str, Any] | None,
) -> None:
    if not tags:
        return
    for key, value in tags.items():
        if value is not None:
            client.set_model_version_tag(model_name, str(version), str(key), str(value))


def _alias_model_version(client: Any, model_name: str, alias: str) -> Any | None:
    _, _, MlflowException = _mlflow_modules()
    try:
        return client.get_model_version_by_alias(model_name, alias)
    except MlflowException:
        return None


def _previous_numeric_version(client: Any, model_name: str, current_version: str) -> str | None:
    try:
        current = int(current_version)
    except ValueError:
        return None
    older = []
    for item in _search_versions(client, model_name):
        try:
            value = int(item.version)
        except ValueError:
            continue
        if value < current:
            older.append(value)
    return str(max(older)) if older else None


def _get_alias_info(model_name: str, alias: str) -> dict[str, Any]:
    _, client, _ = _client()
    version = _alias_model_version(client, model_name, alias)
    if version is None:
        return _empty_alias_info(alias)

    run_id = _string_or_none(getattr(version, "run_id", None))
    run_tags: dict[str, Any] = {}
    run_params: dict[str, Any] = {}
    run_metrics: dict[str, float] = {}
    if run_id:
        run = client.get_run(run_id)
        run_tags = dict(run.data.tags)
        run_params = dict(run.data.params)
        run_metrics = dict(run.data.metrics)

    version_tags = dict(getattr(version, "tags", {}) or {})
    feature_hash = (
        version_tags.get(FEATURE_LIST_HASH_TAG)
        or run_tags.get(FEATURE_LIST_HASH_TAG)
        or run_params.get(FEATURE_LIST_HASH_TAG)
    )
    data_cutoff = (
        version_tags.get("data_cutoff")
        or run_tags.get("data_cutoff")
        or run_params.get("data_cutoff")
        or run_params.get("holdout_quarter")
        or run_params.get("reference_quarter")
    )
    model_path = (
        version_tags.get("model_path")
        or run_tags.get("model_path")
        or run_params.get("model_path")
    )
    return {
        "version": str(version.version),
        "run_id": run_id,
        "feature_list_hash": feature_hash,
        "metrics": run_metrics,
        "alias": alias,
        "data_cutoff": data_cutoff,
        "model_path": model_path,
    }


def _empty_alias_info(alias: str) -> dict[str, Any]:
    return {
        "version": None,
        "run_id": None,
        "feature_list_hash": None,
        "metrics": {},
        "alias": alias,
        "model_path": None,
    }


def _require_cli_tracking_uri() -> None:
    if not os.environ.get("MLFLOW_TRACKING_URI", "").strip():
        raise SystemExit(
            "MLFLOW_TRACKING_URI is not set. Example: "
            "export MLFLOW_TRACKING_URI=http://localhost:${MLFLOW_PORT:-15000}"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage NBO MLflow registry aliases.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--promote", metavar="VERSION", help="Set champion alias to VERSION.")
    group.add_argument("--rollback", action="store_true", help="Rollback champion alias.")
    group.add_argument("--show", action="store_true", help="Show champion/challenger aliases.")
    group.add_argument("--register", metavar="RUN_ID", help="Register RUN_ID artifact as a model.")
    parser.add_argument("--artifact-path", default="model", help="Run artifact path for --register.")
    parser.add_argument("--model-name", default=MODEL_NAME, help="Registered model name.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    _require_cli_tracking_uri()
    if args.promote:
        print(json.dumps(promote(args.promote, args.model_name), ensure_ascii=True, indent=2))
        return
    if args.rollback:
        print(json.dumps(rollback(args.model_name), ensure_ascii=True, indent=2))
        return
    if args.register:
        version = register_model_version(
            args.register,
            artifact_path=args.artifact_path,
            model_name=args.model_name,
        )
        print(json.dumps({"model": args.model_name, "version": version}, indent=2))
        return

    champion = get_champion(args.model_name)
    challenger = get_challenger(args.model_name)
    print(f"model: {args.model_name}")
    print(f"champion: version={champion['version']} run_id={champion['run_id']}")
    print(f"challenger: version={challenger['version']} run_id={challenger['run_id']}")


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    main()
