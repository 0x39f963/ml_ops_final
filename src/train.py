"""Train NBO champion and challenger models."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.multiclass import OneVsRestClassifier

from . import features
from .data_wrappers import load_events, normalize_client_id
from .labels import (
    ENTITY_KEYS,
    POSITIVE_ROLES,
    build_catalog,
    build_labels,
    next_quarter,
    quarter_index,
    to_wide,
)
from .registry import CHALLENGER_ALIAS, log_run, register_model_version, set_alias


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models"
DEFAULT_MIN_SUPPORT = 50
DEFAULT_SEED = 42
DEFAULT_TOP_N = 10
DEFAULT_BACKEND = "logreg"
SEGMENTS = [f"SEG_{idx}" for idx in range(7)]
MODEL_FILE = "model.pkl"
META_FILE = "meta.json"
CATALOG_FILE = "product_catalog.json"
_QUARTER_RE = re.compile(r"^\d{4}Q[1-4]$")


@dataclass
class ChampionModel:
    """Popularity champion with optional co-occurrence from owned products.

    Co-occurrence changes scores only when client_features contains
    owned_products from PIT history. Without it, ranking is global popularity
    plus segment-smoothed prior.
    """

    catalog: list[str]
    global_scores: dict[str, float]
    segment_scores: dict[str, dict[str, float]]
    co_scores: dict[str, dict[str, float]] = field(default_factory=dict)
    alpha: float = 20.0
    co_weight: float = 0.25

    def rank(self, client_features: pd.Series | dict[str, Any], top_n: int | None = None):
        segment = _segment_from_features(client_features)
        base = self.segment_scores.get(segment, self.global_scores)
        scores = {
            product: float(base.get(product, self.global_scores.get(product, 0.0)))
            for product in self.catalog
        }

        owned = _owned_products(client_features)
        if owned:
            for product in self.catalog:
                co_values = [
                    self.co_scores.get(item, {}).get(product, 0.0)
                    for item in owned
                    if item in self.co_scores
                ]
                if co_values:
                    co_score = float(np.mean(co_values))
                    scores[product] = (
                        (1.0 - self.co_weight) * scores[product]
                        + self.co_weight * co_score
                    )

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return ranked if top_n is None else ranked[:top_n]


@dataclass
class ChallengerModel:
    """Supervised multi-label challenger with fixed product order."""

    backend: str
    catalog: list[str]
    feature_names: list[str]
    estimator: Any | None = None
    variable_products: list[str] = field(default_factory=list)
    constants: dict[str, float] = field(default_factory=dict)
    estimators: dict[str, Any] = field(default_factory=dict)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        data = X[self.feature_names] if isinstance(X, pd.DataFrame) else X
        n_rows = len(data)
        out = np.zeros((n_rows, len(self.catalog)), dtype=float)

        for col_idx, product in enumerate(self.catalog):
            out[:, col_idx] = self.constants.get(product, 0.0)

        if self.backend == "logreg" and self.estimator is not None:
            pred = np.asarray(self.estimator.predict_proba(data), dtype=float)
            if pred.ndim == 1:
                pred = pred.reshape(-1, 1)
            for item_idx, product in enumerate(self.variable_products):
                col_idx = self.catalog.index(product)
                out[:, col_idx] = pred[:, item_idx]
        elif self.backend == "lgbm":
            for product, model in self.estimators.items():
                pred = np.asarray(model.predict_proba(data), dtype=float)
                score = pred[:, 1] if pred.ndim == 2 and pred.shape[1] > 1 else pred.ravel()
                col_idx = self.catalog.index(product)
                out[:, col_idx] = score

        return np.clip(out, 0.0, 1.0)

    def predict_proba_topn(self, X: pd.DataFrame, top_n: int) -> list[list[tuple[str, float]]]:
        proba = self.predict_proba(X)
        rows: list[list[tuple[str, float]]] = []
        for row in proba:
            order = sorted(
                range(len(self.catalog)),
                key=lambda idx: (-float(row[idx]), self.catalog[idx]),
            )
            rows.append(
                [(self.catalog[idx], float(row[idx])) for idx in order[:top_n]]
            )
        return rows


def temporal_split(labels: pd.DataFrame, reference_quarter: str) -> tuple[pd.Index, pd.Index]:
    """Return long-label row indices for train Q<=Q_t and holdout Q_t+1."""
    ref_idx = quarter_index(reference_quarter)
    quarter_idx = labels["quarter"].map(quarter_index)
    train_idx = labels.index[quarter_idx <= ref_idx]
    holdout_idx = labels.index[labels["quarter"].eq(next_quarter(reference_quarter))]
    return train_idx, holdout_idx


def train_champion(
    labels_train: pd.DataFrame,
    X_train: pd.DataFrame,
    catalog: list[str],
    *,
    alpha: float = 20.0,
) -> ChampionModel:
    """Train global popularity, segment priors, and co-occurrence scores."""
    work = labels_train.loc[labels_train["product"].isin(catalog)].copy()
    entity_count = max(1, X_train[ENTITY_KEYS].drop_duplicates().shape[0])
    pos = work.loc[work["y"].eq(1)]
    global_counts = pos.groupby("product", dropna=False).size()
    global_scores = {
        product: float(global_counts.get(product, 0) / entity_count)
        for product in catalog
    }

    seg_rows = X_train[ENTITY_KEYS].copy()
    seg_rows["segment"] = X_train.apply(_segment_from_features, axis=1)
    merged = work.merge(seg_rows, on=ENTITY_KEYS, how="left")
    seg_counts = seg_rows.groupby("segment", dropna=False).size()
    seg_pos = merged.loc[merged["y"].eq(1)].groupby(["segment", "product"]).size()

    segment_scores: dict[str, dict[str, float]] = {}
    for segment in sorted(seg_counts.index.astype(str)):
        n_seg = int(seg_counts.get(segment, 0))
        scores: dict[str, float] = {}
        for product in catalog:
            count = int(seg_pos.get((segment, product), 0))
            base = global_scores.get(product, 0.0)
            scores[product] = float((count + alpha * base) / (n_seg + alpha))
        segment_scores[segment] = scores

    co_scores = _co_occurrence_scores(work, catalog)
    return ChampionModel(
        catalog=list(catalog),
        global_scores=global_scores,
        segment_scores=segment_scores,
        co_scores=co_scores,
        alpha=alpha,
    )


def train_challenger(
    X_train: pd.DataFrame,
    Y_train: pd.DataFrame,
    catalog: list[str],
    *,
    backend: str = DEFAULT_BACKEND,
    seed: int = DEFAULT_SEED,
) -> ChallengerModel:
    """Train the supervised multi-label challenger."""
    feature_names = _feature_names_from_matrix(X_train)
    y = Y_train[catalog].astype(int)
    constants: dict[str, float] = {}
    variable_products: list[str] = []

    for product in catalog:
        values = y[product]
        if values.nunique(dropna=False) < 2:
            constants[product] = float(values.iloc[0])
        else:
            variable_products.append(product)

    data = X_train[feature_names]
    backend = backend.lower()
    if backend == "logreg":
        estimator = None
        if variable_products:
            estimator = OneVsRestClassifier(
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=500,
                    random_state=seed,
                    solver="liblinear",
                )
            )
            estimator.fit(data, y[variable_products])
        return ChallengerModel(
            backend=backend,
            catalog=list(catalog),
            feature_names=feature_names,
            estimator=estimator,
            variable_products=variable_products,
            constants=constants,
        )

    if backend == "lgbm":
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise RuntimeError("backend=lgbm requires lightgbm.") from exc

        estimators: dict[str, Any] = {}
        for product in variable_products:
            values = y[product]
            pos_count = int(values.sum())
            neg_count = int(len(values) - pos_count)
            scale = float(neg_count / max(1, pos_count))
            model = lgb.LGBMClassifier(
                n_estimators=120,
                learning_rate=0.05,
                random_state=seed,
                deterministic=True,
                force_col_wise=True,
                scale_pos_weight=scale,
                verbose=-1,
            )
            model.fit(data, values)
            estimators[product] = model
        return ChallengerModel(
            backend=backend,
            catalog=list(catalog),
            feature_names=feature_names,
            variable_products=variable_products,
            constants=constants,
            estimators=estimators,
        )

    raise ValueError("backend must be 'logreg' or 'lgbm'.")


def owned_products_from_events(
    entities,
    cutoff,
    events: pd.DataFrame | None = None,
) -> list[str] | dict[str, list[str]]:
    """Return PIT-owned positive products for champion co-occurrence.

    A single client_id returns list[str]. DataFrame/list input returns a
    dict[client_id, list[str]]. b04/b06 should pass this list as
    client_features["owned_products"] when calling ChampionModel.rank().
    """
    single, client_ids = _client_ids_for_owned(entities)
    if not client_ids:
        return [] if single else {}

    cutoff_ts = _cutoff_ts(cutoff)
    data = _prepare_owned_events(load_events() if events is None else events, cutoff_ts)
    if data.empty:
        empty = {client_id: [] for client_id in client_ids}
        return empty[client_ids[0]] if single else empty

    data = data.loc[data["client_id"].isin(client_ids)].copy()
    owned = (
        data.groupby("client_id", dropna=False)["product"]
        .apply(lambda values: sorted(set(values.astype(str))))
        .to_dict()
    )
    out = {client_id: owned.get(client_id, []) for client_id in client_ids}
    return out[client_ids[0]] if single else out


def save_model(
    champion: ChampionModel,
    challenger: ChallengerModel,
    feature_list: dict[str, Any],
    catalog: list[str],
    metrics: dict[str, Any],
    *,
    model_dir: Path,
    seed: int,
    backend: str,
    min_support: int,
) -> dict[str, Path]:
    """Save the local model artifact and metadata."""
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / MODEL_FILE
    meta_path = model_dir / META_FILE
    catalog_path = model_dir / CATALOG_FILE

    artifact = {"champion": champion, "challenger": challenger, "active": "champion"}
    _prepare_pickle_modules()
    joblib.dump(artifact, model_path)

    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_list_hash": feature_list_hash(feature_list),
        "feature_list": feature_list,
        "product_catalog": list(catalog),
        "seed": int(seed),
        "backend": backend,
        "min_support": int(min_support),
        "metrics": metrics,
        "lib_versions": _lib_versions(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    catalog_path.write_text(
        json.dumps({"product_catalog": list(catalog)}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"model_path": model_path, "meta_path": meta_path, "catalog_path": catalog_path}


def train_model(
    reference_quarter: str,
    *,
    backend: str | None = None,
    min_support: int | None = None,
    seed: int | None = None,
    top_n: int | None = None,
    model_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the full training flow and return a leak-safe summary."""
    _load_dotenv()
    backend = (backend or os.environ.get("BACKEND") or DEFAULT_BACKEND).lower()
    min_support = int(min_support or os.environ.get("MIN_SUPPORT", DEFAULT_MIN_SUPPORT))
    seed = int(seed or os.environ.get("TRAIN_SEED", DEFAULT_SEED))
    top_n = int(top_n or os.environ.get("TOP_N", DEFAULT_TOP_N))
    model_dir_path = _model_dir(model_dir)
    np.random.seed(seed)

    run_id = datetime.now(timezone.utc).strftime("nbo_train_%Y%m%d_%H%M%S")
    events = load_events()
    feature_list = _load_feature_list()
    feature_names = _feature_names(feature_list)

    labels = build_labels(reference_quarter, events=events)
    train_idx, holdout_idx = temporal_split(labels, reference_quarter)
    labels_train = labels.loc[train_idx].reset_index(drop=True)
    labels_holdout = labels.loc[holdout_idx].reset_index(drop=True)
    if labels_train.empty:
        raise ValueError("No train labels were built.")
    if labels_holdout.empty:
        raise ValueError("No holdout labels were built for Q_t+1.")

    catalog = build_catalog(labels_train, min_support)
    if not catalog:
        max_support = _max_support(labels_train)
        raise ValueError(
            f"No products passed min_support={min_support}; max observed support={max_support}."
        )

    train_entities = _entities_from_labels(labels_train)
    holdout_entities = _entities_from_labels(labels_holdout)
    X_train = _build_feature_matrix(train_entities, feature_names, events)
    X_holdout = _build_feature_matrix(holdout_entities, feature_names, events)
    Y_train = _align_y(to_wide(labels_train, catalog), X_train, catalog)
    Y_holdout = _align_y(to_wide(labels_holdout, catalog), X_holdout, catalog)

    champion = train_champion(labels_train, X_train, catalog)
    challenger = train_challenger(
        X_train,
        Y_train,
        catalog,
        backend=backend,
        seed=seed,
    )
    metrics = _metrics(
        challenger,
        X_holdout,
        Y_holdout,
        catalog,
        seed=seed,
        backend=backend,
        min_support=min_support,
        n_train_rows=len(X_train),
        n_holdout_rows=len(X_holdout),
    )

    paths = save_model(
        champion,
        challenger,
        feature_list,
        catalog,
        metrics,
        model_dir=model_dir_path,
        seed=seed,
        backend=backend,
        min_support=min_support,
    )
    feature_hash = feature_list_hash(feature_list)
    holdout_quarter = next_quarter(reference_quarter)
    model_path = paths["model_path"]
    mlflow_run_id = log_run(
        params={
            "run_id": run_id,
            "reference_quarter": reference_quarter,
            "holdout_quarter": holdout_quarter,
            "backend": backend,
            "seed": seed,
            "min_support": min_support,
            "top_n": top_n,
            "model_path": str(model_path),
        },
        metrics=metrics,
        feature_list_hash=feature_hash,
        model_role=CHALLENGER_ALIAS,
        run_name=run_id,
    )
    mlflow_model_version = None
    if mlflow_run_id:
        mlflow_model_version = register_model_version(
            mlflow_run_id,
            tags={
                "feature_list_hash": feature_hash,
                "data_cutoff": holdout_quarter,
                "reference_quarter": reference_quarter,
                "min_support": min_support,
                "backend": backend,
                "model_path": str(model_path),
                "model_artifact_mode": "local_model_path",
            },
        )
        set_alias(CHALLENGER_ALIAS, mlflow_model_version)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "reference_quarter": reference_quarter,
        "holdout_quarter": holdout_quarter,
        "metrics": metrics,
        "feature_list_hash": feature_hash,
        "product_catalog": catalog,
        "model_artifact": MODEL_FILE,
        "meta_artifact": META_FILE,
        "mlflow_run_id": mlflow_run_id,
        "mlflow_model_version": mlflow_model_version,
    }
    _write_train_report(summary)

    return {
        "model_path": str(paths["model_path"]),
        "meta_path": str(paths["meta_path"]),
        "metrics": metrics,
        "run_id": run_id,
        "mlflow_run_id": mlflow_run_id,
        "mlflow_model_version": mlflow_model_version,
    }


def feature_list_hash(feature_list: dict[str, Any]) -> str:
    """Return the project parity-token: schema-only feature_list hash."""
    if isinstance(feature_list.get("hash"), str) and feature_list["hash"]:
        return str(feature_list["hash"])

    items = feature_list.get("features", [])
    if not items:
        raise ValueError("feature_list must contain features or hash.")
    features_payload = []
    for item in items:
        if isinstance(item, dict):
            features_payload.append((str(item.get("name")), str(item.get("dtype"))))
        else:
            features_payload.append((str(item), ""))
    payload = json.dumps(
        features_payload,
        ensure_ascii=True,
        sort_keys=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Train NBO champion and challenger.")
    parser.add_argument("--quarter", required=True, help="Reference quarter Q_t, e.g. 2024Q4.")
    parser.add_argument(
        "--backend",
        default=os.environ.get("BACKEND", DEFAULT_BACKEND),
        choices=["logreg", "lgbm"],
    )
    parser.add_argument(
        "--min-support",
        type=int,
        default=int(os.environ.get("MIN_SUPPORT", DEFAULT_MIN_SUPPORT)),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=int(os.environ.get("TRAIN_SEED", DEFAULT_SEED)),
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=int(os.environ.get("TOP_N", DEFAULT_TOP_N)),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = train_model(
        args.quarter,
        backend=args.backend,
        min_support=args.min_support,
        seed=args.seed,
        top_n=args.top_n,
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))


def _load_feature_list() -> dict[str, Any]:
    path = features.FEATURE_LIST_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"feature_list.json not found at {path}; run b02 feature build first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _feature_names(feature_list: dict[str, Any]) -> list[str]:
    items = feature_list.get("features", [])
    names = [item["name"] if isinstance(item, dict) else str(item) for item in items]
    if not names:
        raise ValueError("feature_list.json does not contain features.")
    return names


def _feature_names_from_matrix(matrix: pd.DataFrame) -> list[str]:
    return [name for name in matrix.columns if name not in ENTITY_KEYS]


def _entities_from_labels(labels: pd.DataFrame) -> pd.DataFrame:
    entities = labels[ENTITY_KEYS].drop_duplicates().copy()
    entities["_q_idx"] = entities["quarter"].map(quarter_index)
    entities = entities.sort_values(["_q_idx", "client_id"]).drop(columns=["_q_idx"])
    return entities.reset_index(drop=True)


def _build_feature_matrix(
    entities: pd.DataFrame,
    feature_names: list[str],
    events: pd.DataFrame,
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for quarter, group in entities.groupby("quarter", sort=True):
        matrix = features.build_features(
            group[ENTITY_KEYS],
            features.quarter_to_cutoff_end(str(quarter)),
            events=events,
        )
        _ensure_columns(matrix, feature_names)
        parts.append(matrix[ENTITY_KEYS + feature_names])

    if not parts:
        return pd.DataFrame(columns=ENTITY_KEYS + feature_names)
    out = pd.concat(parts, ignore_index=True)
    order = entities.assign(_order=np.arange(len(entities)))
    out = order.merge(out, on=ENTITY_KEYS, how="left").sort_values("_order")
    return out.drop(columns=["_order"]).reset_index(drop=True)


def _align_y(wide: pd.DataFrame, X: pd.DataFrame, catalog: list[str]) -> pd.DataFrame:
    aligned = X[ENTITY_KEYS].merge(wide, on=ENTITY_KEYS, how="left")
    for product in catalog:
        aligned[product] = aligned[product].fillna(0).astype("int8")
    return aligned[ENTITY_KEYS + catalog]


def _metrics(
    challenger: ChallengerModel,
    X_holdout: pd.DataFrame,
    Y_holdout: pd.DataFrame,
    catalog: list[str],
    *,
    seed: int,
    backend: str,
    min_support: int,
    n_train_rows: int,
    n_holdout_rows: int,
) -> dict[str, Any]:
    proba = challenger.predict_proba(X_holdout)
    aucs: dict[str, float] = {}
    for idx, product in enumerate(catalog):
        y_true = Y_holdout[product].astype(int)
        if y_true.nunique() < 2:
            continue
        aucs[product] = float(roc_auc_score(y_true, proba[:, idx]))

    macro_auc = float(np.mean(list(aucs.values()))) if aucs else None
    return {
        "n_train_rows": int(n_train_rows),
        "n_holdout_rows": int(n_holdout_rows),
        "n_products_catalog": int(len(catalog)),
        "macro_auc_challenger": macro_auc,
        "seed": int(seed),
        "backend": backend,
        "min_support": int(min_support),
        "n_auc_products": int(len(aucs)),
    }


def _co_occurrence_scores(labels_train: pd.DataFrame, catalog: list[str]) -> dict[str, dict[str, float]]:
    if labels_train.empty or not catalog:
        return {}
    wide = to_wide(labels_train, catalog)
    arr = wide[catalog].to_numpy(dtype=float)
    if arr.size == 0:
        return {}
    counts = arr.sum(axis=0)
    pair = arr.T @ arr
    scores: dict[str, dict[str, float]] = {}
    for row_idx, source in enumerate(catalog):
        denom = max(1.0, float(counts[row_idx]))
        scores[source] = {
            target: float(pair[row_idx, col_idx] / denom)
            for col_idx, target in enumerate(catalog)
            if target != source
        }
    return scores


def _segment_from_features(row: pd.Series | dict[str, Any]) -> str:
    for segment in SEGMENTS:
        if int(_row_get(row, f"seg_{segment}", 0) or 0) == 1:
            return segment
    return "SEG_UNKNOWN"


def _owned_products(row: pd.Series | dict[str, Any]) -> list[str]:
    value = _row_get(row, "owned_products", [])
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    try:
        return [str(item) for item in value]
    except TypeError:
        return []


def _client_ids_for_owned(entities) -> tuple[bool, list[str]]:
    if isinstance(entities, str):
        client_id = normalize_client_id(entities)
        return True, [client_id] if client_id else []

    if isinstance(entities, pd.Series):
        if "client_id" not in entities:
            raise ValueError("Series must contain client_id.")
        client_id = normalize_client_id(entities["client_id"])
        return True, [client_id] if client_id else []

    if isinstance(entities, dict):
        if "client_id" not in entities:
            raise ValueError("Dict must contain client_id.")
        client_id = normalize_client_id(entities["client_id"])
        return True, [client_id] if client_id else []

    if isinstance(entities, pd.DataFrame):
        if "client_id" not in entities.columns:
            raise ValueError("Entities DataFrame must contain client_id.")
        client_ids = entities["client_id"].map(normalize_client_id)
    else:
        items = list(entities)
        if not items:
            return False, []
        if isinstance(items[0], dict):
            client_ids = pd.Series([item.get("client_id", "") for item in items])
        elif isinstance(items[0], (tuple, list)):
            client_ids = pd.Series([item[0] if item else "" for item in items])
        else:
            client_ids = pd.Series(items)
        client_ids = client_ids.map(normalize_client_id)

    clean = [client_id for client_id in client_ids.dropna().astype(str) if client_id]
    return False, sorted(set(clean))


def _cutoff_ts(cutoff) -> pd.Timestamp:
    if isinstance(cutoff, pd.Period):
        return cutoff.asfreq("Q-DEC").end_time
    if isinstance(cutoff, str) and _QUARTER_RE.match(cutoff.strip().upper()):
        return features.quarter_to_cutoff_end(cutoff)
    return pd.to_datetime(cutoff)


def _prepare_owned_events(events: pd.DataFrame, cutoff_ts: pd.Timestamp) -> pd.DataFrame:
    missing = sorted({"client_id", "ts", "product"} - set(events.columns))
    if missing:
        raise ValueError(f"Event data is missing required columns: {missing}")
    role_col = _owned_role_col(events)

    data = events.copy()
    data["client_id"] = data["client_id"].map(normalize_client_id)
    data = data.loc[data["client_id"].ne("")].copy()
    if "inn_is_pseudo" in data.columns:
        data = data.loc[~_as_bool(data["inn_is_pseudo"])].copy()
    data["ts"] = pd.to_datetime(data["ts"])
    data["product"] = data["product"].astype("string").str.strip()
    data["role_norm"] = data[role_col].astype("string").str.strip().str.lower()
    return data.loc[
        data["ts"].le(cutoff_ts)
        & data["product"].notna()
        & data["product"].ne("")
        & data["role_norm"].isin(POSITIVE_ROLES),
        ["client_id", "product"],
    ].drop_duplicates()


def _owned_role_col(events: pd.DataFrame) -> str:
    if "lifecycle_role" in events.columns:
        return "lifecycle_role"
    if "event_type" in events.columns:
        return "event_type"
    raise ValueError("Event data must contain lifecycle_role or event_type.")


def _as_bool(values: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False).astype(bool)
    text = values.astype("string").str.strip().str.lower()
    return text.isin({"1", "true", "yes", "y"})


def _row_get(row: pd.Series | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(row, pd.Series):
        return row.get(key, default)
    return row.get(key, default)


def _model_dir(value: str | Path | None = None) -> Path:
    raw = value if value is not None else os.environ.get("MODEL_DIR", "./models")
    path = Path(os.path.expandvars(str(raw))).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_dotenv() -> None:
    path = PROJECT_ROOT / ".env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), os.path.expandvars(value))


def _write_train_report(summary: dict[str, Any]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "train_run.json"
    safe_summary = _safe_report_value(summary)
    path.write_text(
        json.dumps(safe_summary, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _safe_report_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _safe_report_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_report_value(item) for item in value]
    return value


def _prepare_pickle_modules() -> None:
    ChampionModel.__module__ = "src.train"
    ChallengerModel.__module__ = "src.train"
    if __name__ == "__main__":
        sys.modules["src.train"] = sys.modules[__name__]


def _ensure_columns(data: pd.DataFrame, columns: list[str]) -> None:
    missing = [name for name in columns if name not in data.columns]
    if missing:
        raise ValueError(f"Feature matrix is missing columns: {missing}")


def _max_support(labels_train: pd.DataFrame) -> int:
    counts = labels_train.loc[labels_train["y"].eq(1)].groupby("product").size()
    return int(counts.max()) if not counts.empty else 0


def _lib_versions() -> dict[str, str]:
    versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit_learn": sklearn.__version__,
        "joblib": joblib.__version__,
    }
    try:
        import lightgbm as lgb

        versions["lightgbm"] = lgb.__version__
    except ImportError:
        versions["lightgbm"] = "not_installed"
    return versions


if __name__ == "__main__":
    main()
