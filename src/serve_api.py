"""FastAPI serving for the NBO champion alias.

Prometheus metric contract for b08:
- nbo_requests_total: HTTP requests by endpoint and status_code.
- nbo_errors_total: 5xx and uncaught errors by endpoint.
- nbo_request_latency_seconds: request latency histogram by endpoint.
- nbo_score_distribution: emitted top-N score histogram by model_role.
- nbo_not_scorable_total: population-filtered not_scorable responses.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field, field_validator

from . import features, registry
from .data_wrappers import load_events, load_scoring_registry, normalize_client_id


LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_FILE = "model.pkl"
META_FILE = "meta.json"
PUBLIC_PRODUCTS = [f"PROD_{idx:02d}" for idx in range(1, 40)]
PUBLIC_SEGMENTS = [f"SEG_{idx}" for idx in range(7)]
CHAMPION_ALIAS = registry.CHAMPION_ALIAS
BATCH_LIMIT = 500
ALLOWED_MODES = {"single", "explain"}

# Mirror of features._SYNTH_FAMILY_ALIASES; keep in sync with b02 taxonomy.
FAMILY_ALIASES = {
    "fam_box": "software_box",
    "fam_device": "hardware_license",
    "fam_service": "infra",
    "fam_migration": "infra",
    "fam_subscription": "software_cloud",
    "fam_addon": "addon",
}

STATE: dict[str, Any] = {
    "model": None,
    "model_kind": None,
    "version": None,
    "feature_list_hash": None,
    "metrics": {},
    "data_cutoff": None,
    "alias": CHAMPION_ALIAS,
    "loaded_at": None,
    "model_name": registry.MODEL_NAME,
    "product_catalog": PUBLIC_PRODUCTS,
    "feature_names": [],
    "feature_list": None,
    "scoring_registry": None,
    "product_family_map": {},
    "last_error": None,
}

NBO_REGISTRY = CollectorRegistry()
REQUESTS_TOTAL = Counter(
    "nbo_requests_total",
    "HTTP requests handled by the NBO API.",
    labelnames=("endpoint", "status_code"),
    registry=NBO_REGISTRY,
)
ERRORS_TOTAL = Counter(
    "nbo_errors_total",
    "HTTP 5xx responses and uncaught handler errors.",
    labelnames=("endpoint",),
    registry=NBO_REGISTRY,
)
REQUEST_LATENCY = Histogram(
    "nbo_request_latency_seconds",
    "Request latency in seconds.",
    labelnames=("endpoint",),
    buckets=(0.05, 0.1, 0.25, 0.5, 0.8, 1.0, 2.0),
    registry=NBO_REGISTRY,
)
SCORE_DISTRIBUTION = Histogram(
    "nbo_score_distribution",
    "Distribution of probabilities emitted in top-N responses.",
    labelnames=("model_role",),
    buckets=tuple(round(idx / 10, 1) for idx in range(11)),
    registry=NBO_REGISTRY,
)
NOT_SCORABLE_TOTAL = Counter(
    "nbo_not_scorable_total",
    "Requests filtered out as not_scorable.",
    registry=NBO_REGISTRY,
)


class ScoreRequest(BaseModel):
    client_id: str = Field(..., min_length=1)
    reference_date: str = Field(..., min_length=4)
    mode: str | None = None
    product_family: str | None = None

    model_config = {"extra": "forbid"}

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().lower()
        if normalized not in ALLOWED_MODES:
            raise ValueError("mode must be single or explain.")
        return normalized


class ScoreItem(BaseModel):
    product: str
    p: float
    decision: str
    confidence: str


class ScoreResponse(BaseModel):
    client_id: str
    model_version: str | None
    segment_id: str | None
    status: str
    score: list[ScoreItem] | None
    recommended_action: str
    caveats: list[str]


class BatchScoreRequest(BaseModel):
    client_ids: list[str] = Field(..., min_length=1, max_length=BATCH_LIMIT)
    reference_date: str = Field(..., min_length=4)
    top_n: int | None = Field(default=None, ge=1, le=len(PUBLIC_PRODUCTS))

    model_config = {"extra": "forbid"}


class HealthResponse(BaseModel):
    status: str
    model_version: str | None
    champion_alias: str
    data_cutoff: str | None


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_model()
    yield


app = FastAPI(title="NBO scoring API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def instrument_requests(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)

    endpoint = request.url.path
    started = time.perf_counter()
    status_code = 500
    error_counted = False
    try:
        response = await call_next(request)
        status_code = int(response.status_code)
        return response
    except Exception:
        ERRORS_TOTAL.labels(endpoint=endpoint).inc()
        error_counted = True
        raise
    finally:
        elapsed = time.perf_counter() - started
        REQUEST_LATENCY.labels(endpoint=endpoint).observe(elapsed)
        REQUESTS_TOTAL.labels(endpoint=endpoint, status_code=str(status_code)).inc()
        if status_code >= 500 and not error_counted:
            ERRORS_TOTAL.labels(endpoint=endpoint).inc()


def refresh_model() -> None:
    """Reload the champion alias without restarting the process."""
    load_model()


def load_model() -> None:
    """Load champion metadata, feature contract, population, and model bytes."""
    model_name = os.environ.get("MLFLOW_MODEL_NAME", registry.MODEL_NAME)
    feature_list = _read_feature_list()
    local_hash = feature_list.get("hash")
    feature_names = _feature_names(feature_list)
    data_cutoff = None
    champion: dict[str, Any] = {}
    model = None
    model_kind = None
    last_error = None

    try:
        champion = registry.get_champion(model_name=model_name)
    except Exception as exc:
        champion = _empty_champion_info()
        last_error = f"registry unavailable: {exc}"
        LOGGER.warning("Champion alias lookup failed: %s", exc)

    data_cutoff = _resolve_data_cutoff(champion)
    champion_hash = champion.get("feature_list_hash")
    version = champion.get("version")

    if champion_hash and local_hash and champion_hash != local_hash:
        last_error = "feature_list_hash mismatch between champion and local contract"
        LOGGER.warning(last_error)
    elif version:
        model = _load_mlflow_model(model_name)
        model_kind = "mlflow_pyfunc" if model is not None else None
        if model is None:
            model, model_kind = _load_local_model(
                champion.get("model_path"),
                local_hash,
                role=CHAMPION_ALIAS,
            )
        if model is None and not last_error:
            last_error = "champion model bytes are unavailable"
    else:
        last_error = "champion alias is not assigned"

    product_catalog = _product_catalog(model)
    if not product_catalog:
        product_catalog = _catalog_from_meta() or PUBLIC_PRODUCTS

    STATE.update(
        {
            "model": model,
            "model_kind": model_kind,
            "version": str(version) if version else None,
            "feature_list_hash": champion_hash or local_hash,
            "metrics": champion.get("metrics") or {},
            "data_cutoff": data_cutoff,
            "alias": CHAMPION_ALIAS,
            "loaded_at": _now_local(),
            "model_name": model_name,
            "product_catalog": product_catalog,
            "feature_names": feature_names,
            "feature_list": feature_list,
            "scoring_registry": _load_population_registry(),
            "product_family_map": _load_product_family_map(),
            "last_error": last_error,
        }
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        status = "ok" if STATE.get("model") is not None else "degraded"
        return HealthResponse(
            status=status,
            model_version=STATE.get("version"),
            champion_alias=CHAMPION_ALIAS,
            data_cutoff=STATE.get("data_cutoff"),
        )
    except Exception:
        return HealthResponse(
            status="degraded",
            model_version=None,
            champion_alias=CHAMPION_ALIAS,
            data_cutoff=None,
        )


@app.post("/score", response_model=ScoreResponse)
def score(request: ScoreRequest) -> ScoreResponse:
    _refresh_if_requested()
    top_n = _default_top_n()
    try:
        responses = _score_clients(
            [request.client_id],
            request.reference_date,
            top_n,
            product_family=request.product_family,
        )
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("Score request failed.")
        raise HTTPException(status_code=500, detail="internal scoring error") from exc
    return responses[0]


@app.post("/batch-score", response_model=list[ScoreResponse])
def batch_score(request: BatchScoreRequest) -> list[ScoreResponse]:
    _refresh_if_requested()
    top_n = request.top_n or _default_top_n()
    if len(request.client_ids) > BATCH_LIMIT:
        raise HTTPException(status_code=413, detail="batch size limit exceeded")
    try:
        return _score_clients(request.client_ids, request.reference_date, top_n)
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("Batch score request failed.")
        raise HTTPException(status_code=500, detail="internal scoring error") from exc


@app.get("/model-info")
def model_info() -> dict[str, Any]:
    registry_info: dict[str, Any] = {}
    try:
        registry_info = registry.get_model_info(model_name=STATE.get("model_name"))
    except Exception as exc:
        registry_info = {"error": str(exc)}

    return {
        "model_name": STATE.get("model_name"),
        "version": STATE.get("version"),
        "alias": STATE.get("alias"),
        "metrics": STATE.get("metrics") or {},
        "feature_list_hash": STATE.get("feature_list_hash"),
        "data_cutoff": STATE.get("data_cutoff"),
        "loaded_at": STATE.get("loaded_at"),
        "status": "ok" if STATE.get("model") is not None else "degraded",
        "registry": registry_info,
    }


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(NBO_REGISTRY), media_type=CONTENT_TYPE_LATEST)


def _score_clients(
    client_ids: list[str],
    reference_date: str,
    top_n: int,
    product_family: str | None = None,
) -> list[ScoreResponse]:
    if STATE.get("model") is None:
        raise HTTPException(status_code=503, detail="champion model is not loaded")

    quarter = _effective_quarter(reference_date)
    normalized = [normalize_client_id(client_id) for client_id in client_ids]
    responses: list[ScoreResponse | None] = [None] * len(client_ids)
    scorable_rows: list[tuple[int, str]] = []

    for idx, client_id in enumerate(normalized):
        reason = _not_scorable_reason(client_id)
        if reason:
            NOT_SCORABLE_TOTAL.inc()
            responses[idx] = _not_scorable_response(client_id, quarter, reason)
        else:
            scorable_rows.append((idx, client_id))

    if scorable_rows:
        entities = pd.DataFrame(
            {
                "client_id": [client_id for _, client_id in scorable_rows],
                "quarter": quarter,
            }
        )
        matrix = features.get_features(entities, quarter)
        _assert_feature_parity(matrix)
        matrix = _align_matrix_order(matrix, entities)
        predictions = _predict_rows(matrix)

        for row_idx, (original_idx, client_id) in enumerate(scorable_rows):
            row = matrix.iloc[row_idx]
            ranked = _rank_scores(
                predictions[row_idx],
                top_n=top_n,
                product_family=product_family,
            )
            score_items = [_score_item(product, p) for product, p in ranked]
            for item in score_items:
                SCORE_DISTRIBUTION.labels(model_role=CHAMPION_ALIAS).observe(item.p)
            responses[original_idx] = ScoreResponse(
                client_id=client_id,
                model_version=STATE.get("version"),
                segment_id=_segment_from_row(row),
                status="scorable",
                score=score_items,
                recommended_action=_recommended_action(score_items),
                caveats=_base_caveats(quarter),
            )

    return [item for item in responses if item is not None]


def _predict_rows(matrix: pd.DataFrame) -> list[dict[str, float]]:
    model = STATE.get("model")
    feature_names = STATE.get("feature_names") or []
    catalog = _product_catalog(model) or STATE.get("product_catalog") or PUBLIC_PRODUCTS
    X = matrix[feature_names].copy()

    if hasattr(model, "predict_proba"):
        proba = np.asarray(model.predict_proba(X), dtype=float)
        if proba.ndim == 1:
            proba = proba.reshape(-1, 1)
        if proba.shape[1] != len(catalog):
            raise RuntimeError("model probability output does not match product catalog")
        return [
            {product: float(np.clip(value, 0.0, 1.0)) for product, value in zip(catalog, row)}
            for row in proba
        ]

    if hasattr(model, "rank"):
        rows: list[dict[str, float]] = []
        for _, row in matrix.iterrows():
            ranked = model.rank(row, top_n=None)
            rows.append({product: float(np.clip(p, 0.0, 1.0)) for product, p in ranked})
        return rows

    if hasattr(model, "predict"):
        raw = model.predict(X)
        if isinstance(raw, pd.DataFrame):
            rows = raw.to_dict(orient="records")
            return [
                {str(product): float(np.clip(score, 0.0, 1.0)) for product, score in row.items()}
                for row in rows
            ]
        raise RuntimeError("model predict output is not a product score table")

    raise RuntimeError("loaded model does not expose a supported scoring method")


def _rank_scores(
    scores: dict[str, float],
    *,
    top_n: int,
    product_family: str | None,
) -> list[tuple[str, float]]:
    family = _canonical_family(product_family) if product_family else None
    product_family_map = STATE.get("product_family_map") or {}
    items = []
    for product, score in scores.items():
        if family and product_family_map.get(product) != family:
            continue
        if not _is_public_product(product):
            continue
        items.append((product, float(np.clip(score, 0.0, 1.0))))
    items.sort(key=lambda item: (-item[1], item[0]))
    return items[: max(1, min(int(top_n), len(PUBLIC_PRODUCTS)))]


def _score_item(product: str, p: float) -> ScoreItem:
    p = float(np.clip(p, 0.0, 1.0))
    threshold = _decision_threshold()
    if p >= 0.7:
        confidence = "high"
    elif p >= 0.4:
        confidence = "medium"
    else:
        confidence = "low"
    return ScoreItem(
        product=product,
        p=round(p, 6),
        decision="recommend" if p >= threshold else "hold",
        confidence=confidence,
    )


def _not_scorable_response(
    client_id: str,
    quarter: str,
    reason: str,
) -> ScoreResponse:
    return ScoreResponse(
        client_id=client_id,
        model_version=STATE.get("version"),
        segment_id=None,
        status="not_scorable",
        score=None,
        recommended_action="no scoring: client not in scorable population",
        caveats=[*_base_caveats(quarter), f"not_scorable reason = {reason}"],
    )


def _not_scorable_reason(client_id: str) -> str | None:
    if not client_id:
        return "missing client_id"

    scoring_registry = STATE.get("scoring_registry")
    if scoring_registry is None or scoring_registry.empty:
        return None
    if client_id not in scoring_registry.index:
        return "no client mapping"

    row = scoring_registry.loc[client_id]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    status = str(row.get("scoring_status", "SCORABLE")).strip().upper()
    if status != "SCORABLE":
        return "low evidence or no public entity mapping"
    event_count = row.get("event_count")
    if pd.notna(event_count) and int(event_count) < 2:
        return "low evidence"
    return None


def _assert_feature_parity(matrix: pd.DataFrame) -> None:
    local_hash = (STATE.get("feature_list") or {}).get("hash")
    expected_hash = STATE.get("feature_list_hash")
    if expected_hash and local_hash and expected_hash != local_hash:
        raise HTTPException(status_code=503, detail="feature parity mismatch")

    feature_names = STATE.get("feature_names") or []
    missing = [name for name in feature_names if name not in matrix.columns]
    if missing:
        raise HTTPException(status_code=503, detail="feature parity mismatch")


def _align_matrix_order(matrix: pd.DataFrame, entities: pd.DataFrame) -> pd.DataFrame:
    feature_names = STATE.get("feature_names") or []
    ordered = entities.assign(_order=np.arange(len(entities)))
    out = ordered.merge(matrix, on=["client_id", "quarter"], how="left").sort_values("_order")
    return out.drop(columns=["_order"])[["client_id", "quarter", *feature_names]].reset_index(drop=True)


def _segment_from_row(row: pd.Series) -> str | None:
    for segment in PUBLIC_SEGMENTS:
        if int(row.get(f"seg_{segment}", 0) or 0) == 1:
            return segment
    return None


def _recommended_action(items: list[ScoreItem]) -> str:
    if not items:
        return "no scoring: no product candidates after filters"
    return f"offer top product {items[0].product}"


def _base_caveats(quarter: str) -> list[str]:
    return [
        "value is propensity proxy only, not revenue",
        f"cutoff = latest completed quarter ({quarter})",
    ]


def _refresh_if_requested() -> None:
    if os.environ.get("MODEL_REFRESH_ON_REQUEST", "false").strip().lower() in {"1", "true", "yes"}:
        refresh_model()


def _default_top_n() -> int:
    raw = os.environ.get("TOP_N", "10")
    try:
        return max(1, min(int(raw), len(PUBLIC_PRODUCTS)))
    except ValueError:
        return 10


def _decision_threshold() -> float:
    raw = os.environ.get("SCORE_DECISION_THRESHOLD", "0.5")
    try:
        return float(np.clip(float(raw), 0.0, 1.0))
    except ValueError:
        return 0.5


def _effective_quarter(reference_date: str) -> str:
    requested = _quarter_from_any(reference_date)
    data_cutoff = STATE.get("data_cutoff")
    if data_cutoff:
        try:
            cutoff = _quarter_from_any(data_cutoff)
        except ValueError:
            return requested
        if _quarter_index(requested) > _quarter_index(cutoff):
            return cutoff
    return requested


def _quarter_from_any(value: str) -> str:
    cutoff = features.quarter_to_cutoff_end(value)
    period = pd.Timestamp(cutoff).to_period("Q-DEC")
    return f"{period.year}Q{period.quarter}"


def _quarter_index(value: str) -> int:
    quarter = _quarter_from_any(value)
    year, q = quarter.split("Q")
    return int(year) * 4 + int(q) - 1


def _resolve_data_cutoff(champion: dict[str, Any]) -> str:
    for value in (
        champion.get("data_cutoff"),
        os.environ.get("DATA_CUTOFF"),
    ):
        if value:
            return _quarter_from_any(str(value))
    return _latest_completed_quarter()


def _latest_completed_quarter() -> str:
    current = pd.Timestamp.now().to_period("Q-DEC")
    previous = current - 1
    return f"{previous.year}Q{previous.quarter}"


def _read_feature_list() -> dict[str, Any]:
    path = features.FEATURE_LIST_PATH
    if not path.is_file():
        raise FileNotFoundError(f"feature_list.json not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _feature_names(feature_list: dict[str, Any]) -> list[str]:
    names = [str(item["name"]) for item in feature_list.get("features", [])]
    if not names:
        raise ValueError("feature_list.json has no features")
    return names


def _load_mlflow_model(model_name: str) -> Any | None:
    try:
        import mlflow

        tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        model = mlflow.pyfunc.load_model(f"models:/{model_name}@{CHAMPION_ALIAS}")
        if _has_product_scoring_interface(model):
            return model
        LOGGER.warning("MLflow artifact does not expose an NBO product scoring interface.")
        return None
    except Exception as exc:
        LOGGER.warning("MLflow model load skipped: %s", exc)
        return None


def _has_product_scoring_interface(model: Any) -> bool:
    return bool(
        hasattr(model, "predict_proba")
        or hasattr(model, "rank")
        or _product_catalog(model)
    )


def _load_local_model(
    tagged_model_path: str | None,
    local_hash: str | None,
    role: str = CHAMPION_ALIAS,
) -> tuple[Any | None, str | None]:
    model_path = _resolve_model_path(tagged_model_path, local_hash)
    if model_path is None or not model_path.is_file():
        return None, None

    try:
        artifact = joblib.load(model_path)
    except Exception as exc:
        LOGGER.warning("Local model load failed from %s: %s", model_path, exc)
        return None, None

    if isinstance(artifact, dict):
        active = str(artifact.get("active", role) or role)
        wanted = role if role in artifact else active
        if wanted in artifact:
            return artifact[wanted], f"local_joblib_{wanted}"
        if CHAMPION_ALIAS in artifact:
            return artifact[CHAMPION_ALIAS], "local_joblib_champion"
        if registry.CHALLENGER_ALIAS in artifact:
            return artifact[registry.CHALLENGER_ALIAS], "local_joblib_challenger"
    return artifact, "local_joblib"


def _resolve_model_path(tagged_model_path: str | None, local_hash: str | None) -> Path | None:
    candidates: list[Path] = []
    if tagged_model_path:
        candidates.append(_project_path(tagged_model_path))

    model_dir = os.environ.get("MODEL_DIR", str(PROJECT_ROOT / "models"))
    candidates.append(_project_path(model_dir) / MODEL_FILE)

    for path in candidates:
        if not path.is_file():
            continue
        if tagged_model_path and path == _project_path(tagged_model_path):
            return path
        if _local_meta_hash_matches(local_hash):
            return path
    return None


def _project_path(value: str) -> Path:
    path = Path(os.path.expandvars(value)).expanduser()
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _local_meta_hash_matches(local_hash: str | None) -> bool:
    if not local_hash:
        return True
    meta_path = _project_path(os.environ.get("MODEL_DIR", str(PROJECT_ROOT / "models"))) / META_FILE
    if not meta_path.is_file():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return meta.get("feature_list_hash") == local_hash


def _catalog_from_meta() -> list[str]:
    meta_path = _project_path(os.environ.get("MODEL_DIR", str(PROJECT_ROOT / "models"))) / META_FILE
    if not meta_path.is_file():
        return []
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return _clean_catalog(meta.get("product_catalog", []))


def _product_catalog(model: Any | None) -> list[str]:
    if model is None:
        return []
    return _clean_catalog(getattr(model, "catalog", []))


def _clean_catalog(values: Any) -> list[str]:
    if values is None:
        return []
    try:
        items = [str(item) for item in values]
    except TypeError:
        return []
    return [item for item in items if _is_public_product(item)]


def _load_population_registry() -> pd.DataFrame | None:
    try:
        data = load_scoring_registry().copy()
    except Exception as exc:
        LOGGER.warning("Scoring registry unavailable: %s", exc)
        return None
    if "client_id" not in data.columns:
        return None
    data["client_id"] = data["client_id"].map(normalize_client_id)
    data = data.loc[data["client_id"].ne("")].drop_duplicates("client_id", keep="last")
    return data.set_index("client_id", drop=False)


def _load_product_family_map() -> dict[str, str]:
    try:
        events = load_events()
    except Exception as exc:
        LOGGER.warning("Product family map unavailable: %s", exc)
        return {}
    if not {"product", "product_family"}.issubset(events.columns):
        return {}

    mapping: dict[str, str] = {}
    pairs = events[["product", "product_family"]].dropna().drop_duplicates()
    for _, row in pairs.iterrows():
        product = str(row["product"]).strip()
        family = _canonical_family(row["product_family"])
        if _is_public_product(product) and family:
            mapping.setdefault(product, family)
    return mapping


def _canonical_family(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    key = str(value).strip().lower()
    if not key:
        return None
    return FAMILY_ALIASES.get(key, key)


def _is_public_product(value: str) -> bool:
    return isinstance(value, str) and value.startswith("PROD_") and value in PUBLIC_PRODUCTS


def _empty_champion_info() -> dict[str, Any]:
    return {
        "version": None,
        "run_id": None,
        "feature_list_hash": None,
        "metrics": {},
        "alias": CHAMPION_ALIAS,
        "data_cutoff": None,
        "model_path": None,
    }


def _now_local() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
