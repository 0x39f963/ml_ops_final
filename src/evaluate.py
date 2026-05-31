# Generated at: 2026-05-31 22:33:57 MSK
"""Offline holdout evaluation for NBO champion and challenger models."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from . import features
from .data_wrappers import load_events, load_scoring_registry
from .labels import ENTITY_KEYS, build_labels, quarter_from_index, quarter_index, to_wide
from .train import feature_list_hash, owned_products_from_events


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
DATA_DIR = PROJECT_ROOT / "data"
MODEL_DIR = PROJECT_ROOT / "models"
MODEL_FILE = "model.pkl"
META_FILE = "meta.json"
CATALOG_FILE = "product_catalog.json"
TRAIN_RUN_FILE = "train_run.json"
FEATURE_LIST_PATH = PROJECT_ROOT / "artifacts" / "feature_list.json"
K = 10
DEFAULT_SEED = 42
SCORABLE_STATUSES = {"SCORABLE", "PROVISIONAL", "LOW_EVIDENCE", ""}
NOT_SCORABLE_STATUSES = {"NOT_SCORABLE", "NO_INN", "NO_CLIENT_ID"}


@dataclass
class HoldoutData:
    X_holdout: pd.DataFrame
    Y_holdout: pd.DataFrame
    product_list: list[str]
    holdout_quarter: str
    events: pd.DataFrame
    client_status: pd.Series
    segments: pd.Series


@dataclass
class ModelBundle:
    champion: Any
    challenger: Any
    source: str
    meta: dict[str, Any]
    model_path: Path | None


@dataclass
class _StubChampion:
    catalog: list[str]

    def rank(self, client_features: pd.Series | dict[str, Any], top_n: int | None = None):
        del client_features
        scores = {
            product: float((len(self.catalog) - idx) / max(1, len(self.catalog)))
            for idx, product in enumerate(self.catalog)
        }
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return ranked if top_n is None else ranked[:top_n]


@dataclass
class _StubChallenger:
    catalog: list[str]
    seed: int = DEFAULT_SEED

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        rows = []
        client_ids = (
            X["client_id"].astype(str).tolist()
            if isinstance(X, pd.DataFrame) and "client_id" in X.columns
            else [str(idx) for idx in range(len(X))]
        )
        for client_id in client_ids:
            row = []
            for product in self.catalog:
                token = f"{self.seed}:{client_id}:{product}".encode("utf-8")
                digest = hashlib.sha256(token).hexdigest()[:12]
                row.append(int(digest, 16) / float(16**12 - 1))
            rows.append(row)
        return np.asarray(rows, dtype=float)


def top_k_indices(scores: np.ndarray, k: int = K) -> np.ndarray:
    """Return deterministic top-k column indices per row."""
    matrix = _as_score_matrix(scores)
    if k < 1:
        raise ValueError("k must be >= 1.")
    n_rows, n_products = matrix.shape
    k_eff = min(k, n_products)
    out = np.empty((n_rows, k_eff), dtype=int)
    tie_break = np.arange(n_products)
    clean = np.nan_to_num(matrix, nan=-np.inf, posinf=np.inf, neginf=-np.inf)
    for row_idx, row in enumerate(clean):
        out[row_idx] = np.lexsort((tie_break, -row))[:k_eff]
    return out


def precision_at_k(Y_true: np.ndarray, scores: np.ndarray, k: int = K) -> float:
    """Mean relevant share in top-k over all scorable rows."""
    y, s = _aligned_arrays(Y_true, scores)
    if y.size == 0 or y.shape[0] == 0:
        return 0.0
    order = top_k_indices(s, k)
    if order.shape[1] == 0:
        return 0.0
    hits = _hits_at_order(y, order)
    return float(np.mean(hits.sum(axis=1) / order.shape[1]))


def recall_at_k(Y_true: np.ndarray, scores: np.ndarray, k: int = K) -> float:
    """Mean recall in top-k over rows with at least one positive label."""
    y, s = _aligned_arrays(Y_true, scores)
    positives = y.sum(axis=1)
    mask = positives > 0
    if not np.any(mask):
        return 0.0
    order = top_k_indices(s[mask], k)
    hits = _hits_at_order(y[mask], order).sum(axis=1)
    return float(np.mean(hits / positives[mask]))


def map_at_k(Y_true: np.ndarray, scores: np.ndarray, k: int = K) -> float:
    """Mean AP@k over rows with at least one positive label."""
    y, s = _aligned_arrays(Y_true, scores)
    positives = y.sum(axis=1)
    mask = positives > 0
    if not np.any(mask):
        return 0.0
    order = top_k_indices(s[mask], k)
    rel = _hits_at_order(y[mask], order)
    if rel.shape[1] == 0:
        return 0.0
    ranks = np.arange(1, rel.shape[1] + 1, dtype=float)
    precision_by_rank = np.cumsum(rel, axis=1) / ranks
    denom = np.minimum(positives[mask], rel.shape[1])
    ap = (precision_by_rank * rel).sum(axis=1) / denom
    return float(np.mean(ap))


def ndcg_at_k(Y_true: np.ndarray, scores: np.ndarray, k: int = K) -> float:
    """Mean NDCG@k over rows with at least one positive label."""
    y, s = _aligned_arrays(Y_true, scores)
    positives = y.sum(axis=1)
    mask = positives > 0
    if not np.any(mask):
        return 0.0
    order = top_k_indices(s[mask], k)
    rel = _hits_at_order(y[mask], order)
    if rel.shape[1] == 0:
        return 0.0
    discounts = 1.0 / np.log2(np.arange(2, rel.shape[1] + 2, dtype=float))
    dcg = (rel * discounts).sum(axis=1)
    ideal_counts = np.minimum(positives[mask].astype(int), rel.shape[1])
    idcg = np.asarray([discounts[:count].sum() for count in ideal_counts], dtype=float)
    valid = idcg > 0
    if not np.any(valid):
        return 0.0
    return float(np.mean(dcg[valid] / idcg[valid]))


def hit_rate_at_k(Y_true: np.ndarray, scores: np.ndarray, k: int = K) -> float:
    """Share of scorable rows with at least one relevant product in top-k."""
    y, s = _aligned_arrays(Y_true, scores)
    if y.size == 0 or y.shape[0] == 0:
        return 0.0
    order = top_k_indices(s, k)
    if order.shape[1] == 0:
        return 0.0
    hits = _hits_at_order(y, order)
    return float(np.mean(hits.sum(axis=1) > 0))


def per_product_auc(
    Y_true: np.ndarray | pd.DataFrame,
    scores: np.ndarray,
    product_list: list[str] | None = None,
) -> tuple[dict[str, float | None], float | None]:
    """Return per-product ROC-AUC and macro mean over two-class products."""
    names = _product_names(Y_true, product_list)
    y, s = _aligned_arrays(Y_true, scores)
    values: dict[str, float | None] = {}
    auc_values: list[float] = []
    for idx, product in enumerate(names):
        labels = y[:, idx]
        if np.unique(labels).size < 2:
            values[product] = None
            continue
        auc = float(roc_auc_score(labels, s[:, idx]))
        values[product] = auc
        auc_values.append(auc)
    macro = float(np.mean(auc_values)) if auc_values else None
    return values, macro


def coverage(scores: np.ndarray, client_status: pd.Series | None = None) -> dict[str, float | int]:
    """Return scorable and not-scorable shares for rows with score attempts."""
    matrix = _as_score_matrix(scores)
    total = int(matrix.shape[0])
    if total == 0:
        return {
            "scorable_share": 0.0,
            "not_scorable_share": 0.0,
            "n_scorable": 0,
            "n_not_scorable": 0,
        }
    mask = _scorable_mask(matrix, client_status)
    n_scorable = int(mask.sum())
    n_not = int(total - n_scorable)
    return {
        "scorable_share": float(n_scorable / total),
        "not_scorable_share": float(n_not / total),
        "n_scorable": n_scorable,
        "n_not_scorable": n_not,
    }


def load_holdout(cutoff_quarter: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the holdout feature matrix and wide label matrix."""
    data = _load_holdout_data(cutoff_quarter)
    return data.X_holdout, data.Y_holdout


def load_models() -> tuple[Any, Any]:
    """Load b03 champion/challenger artifacts or deterministic CI stubs."""
    _load_dotenv()
    model_dir = _model_dir(None)
    catalog = _resolve_product_catalog(model_dir)
    bundle = _load_models_with_metadata(catalog, model_dir)
    return bundle.champion, bundle.challenger


def evaluate(
    cutoff_quarter: str | None = None,
    *,
    reports_dir: str | Path | None = None,
    model_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run full b04 offline evaluation and write JSON plus markdown reports."""
    _load_dotenv()
    out_dir = _reports_dir(reports_dir)
    model_dir_path = _model_dir(model_dir)
    product_list = _resolve_product_catalog(model_dir_path)
    feature_list = _read_feature_list()
    _check_feature_list(feature_list)

    holdout = _load_holdout_data(
        cutoff_quarter,
        product_list=product_list,
        feature_list=feature_list,
    )
    bundle = _load_models_with_metadata(product_list, model_dir_path)
    _check_model_feature_parity(bundle.meta, feature_list)

    challenger_scores = _scores_from_challenger(
        bundle.challenger,
        holdout.X_holdout,
        holdout.product_list,
    )
    champion_scores = _scores_from_champion(
        bundle.champion,
        holdout.X_holdout,
        holdout.product_list,
        holdout.holdout_quarter,
        holdout.events,
    )

    challenger_mask = _scorable_mask(challenger_scores, holdout.client_status)
    champion_mask = _scorable_mask(champion_scores, holdout.client_status)
    eval_mask = challenger_mask & champion_mask
    Y_true = holdout.Y_holdout[holdout.product_list].to_numpy(dtype=int)
    Y_eval = Y_true[eval_mask]
    challenger_eval = challenger_scores[eval_mask]
    champion_eval = champion_scores[eval_mask]

    challenger_metrics = _metric_suite(Y_eval, challenger_eval, holdout.product_list, K)
    champion_metrics = _metric_suite(Y_eval, champion_eval, holdout.product_list, K)
    coverage_stats = coverage(challenger_scores, holdout.client_status)
    uplift = _uplift(challenger_metrics, champion_metrics)
    calibration_value, calibration_table = calibration_gap(Y_eval, challenger_eval)
    segment_rows = _segment_breakdown(
        holdout.segments.loc[eval_mask].reset_index(drop=True),
        Y_eval,
        challenger_eval,
        K,
    )

    result = {
        "generated_at": _generated_at(),
        "holdout_quarter": holdout.holdout_quarter,
        "k": int(K),
        "n_clients_eval": int(Y_eval.shape[0]),
        "n_products": int(len(holdout.product_list)),
        "model_source": bundle.source,
        "feature_list_hash": feature_list_hash(feature_list),
        "precision_at_10": challenger_metrics["precision_at_10"],
        "recall_at_10": challenger_metrics["recall_at_10"],
        "map_at_10": challenger_metrics["map_at_10"],
        "ndcg_at_10": challenger_metrics["ndcg_at_10"],
        "hit_rate_at_10": challenger_metrics["hit_rate_at_10"],
        "per_product_auc_macro": challenger_metrics["per_product_auc_macro"],
        "per_product_auc": challenger_metrics["per_product_auc"],
        "uplift_vs_popularity": uplift,
        "challenger": challenger_metrics,
        "champion": champion_metrics,
        "scorable_share": coverage_stats["scorable_share"],
        "not_scorable_share": coverage_stats["not_scorable_share"],
        "coverage": coverage_stats,
        "calibration_gap": calibration_value,
        "calibration_table": calibration_table,
    }
    result = _json_ready(result)

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "metric_report.json"
    md_path = out_dir / "metric_report.md"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(
        _render_markdown(result, segment_rows, bundle.meta),
        encoding="utf-8",
    )
    return result


def calibration_gap(
    Y_true: np.ndarray,
    scores: np.ndarray,
    n_bins: int = 10,
) -> tuple[float, list[dict[str, float | int]]]:
    """Mean absolute gap between predicted probability and observed labels."""
    y, s = _aligned_arrays(Y_true, scores)
    if y.size == 0:
        return 0.0, []
    pred = np.clip(s.ravel(), 0.0, 1.0)
    obs = y.ravel()
    finite = np.isfinite(pred)
    pred = pred[finite]
    obs = obs[finite]
    if pred.size == 0:
        return 0.0, []

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bucket_ids = np.digitize(pred, bins[1:-1], right=True)
    rows: list[dict[str, float | int]] = []
    gaps: list[float] = []
    for bucket in range(n_bins):
        mask = bucket_ids == bucket
        if not np.any(mask):
            continue
        mean_pred = float(np.mean(pred[mask]))
        observed = float(np.mean(obs[mask]))
        gap = abs(mean_pred - observed)
        gaps.append(gap)
        rows.append(
            {
                "bucket": int(bucket),
                "n": int(mask.sum()),
                "predicted_p": mean_pred,
                "observed_rate": observed,
                "abs_gap": gap,
            }
        )
    return (float(np.mean(gaps)) if gaps else 0.0), rows


def main() -> None:
    args = _parse_args()
    result = evaluate(args.cutoff)
    summary = {
        "holdout_quarter": result["holdout_quarter"],
        "precision_at_10": result["precision_at_10"],
        "hit_rate_at_10": result["hit_rate_at_10"],
        "uplift_vs_popularity": result["uplift_vs_popularity"],
        "report_json": str(REPORTS_DIR / "metric_report.json"),
        "report_md": str(REPORTS_DIR / "metric_report.md"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate NBO model on temporal holdout.")
    parser.add_argument(
        "--cutoff",
        default=None,
        help="Holdout reference quarter Q_t+1, for example 2022Q1.",
    )
    return parser.parse_args()


def _load_holdout_data(
    cutoff_quarter: str | None,
    *,
    product_list: list[str] | None = None,
    feature_list: dict[str, Any] | None = None,
) -> HoldoutData:
    _load_dotenv()
    events = load_events()
    holdout_quarter = _format_quarter(
        cutoff_quarter or _default_holdout_quarter(events)
    )
    reference_quarter = _previous_quarter(holdout_quarter)
    labels_all = build_labels(reference_quarter, events=events)
    labels_holdout = labels_all.loc[labels_all["quarter"].eq(holdout_quarter)].copy()
    if labels_holdout.empty:
        raise ValueError(f"No holdout labels were built for {holdout_quarter}.")

    catalog = product_list or _catalog_from_labels(labels_all, reference_quarter)
    if not catalog:
        raise ValueError("Product catalog is empty; train b03 or provide model metadata.")

    feature_info = _read_feature_list() if feature_list is None else feature_list
    feature_names = _feature_names(feature_info)
    entities = _entities_from_labels(labels_holdout)
    X_holdout = _build_feature_matrix(entities, feature_names, events)
    Y_holdout = _align_y(to_wide(labels_holdout, catalog), X_holdout, catalog)
    quarters = set(Y_holdout["quarter"].astype(str))
    if quarters != {holdout_quarter}:
        raise AssertionError(
            f"Holdout leakage guard failed: expected {holdout_quarter}, got {sorted(quarters)}."
        )

    statuses = _client_status(X_holdout["client_id"])
    segments = _segments_from_features(X_holdout)
    return HoldoutData(
        X_holdout=X_holdout,
        Y_holdout=Y_holdout,
        product_list=list(catalog),
        holdout_quarter=holdout_quarter,
        events=events,
        client_status=statuses,
        segments=segments,
    )


def _load_models_with_metadata(
    product_list: list[str],
    model_dir: Path,
) -> ModelBundle:
    model_path = model_dir / MODEL_FILE
    meta = _read_model_meta(model_dir)
    if model_path.is_file():
        artifact = joblib.load(model_path)
        if isinstance(artifact, dict):
            champion = artifact.get("champion")
            challenger = artifact.get("challenger")
        else:
            champion = getattr(artifact, "champion", None)
            challenger = getattr(artifact, "challenger", None)
        if champion is None or challenger is None:
            raise ValueError(f"Model artifact {model_path} must contain champion and challenger.")
        return ModelBundle(
            champion=champion,
            challenger=challenger,
            source="b03_model_artifact",
            meta=meta,
            model_path=model_path,
        )

    meta.setdefault("assumption", "b03 model.pkl is local-only or absent; deterministic CI stubs used.")
    return ModelBundle(
        champion=_StubChampion(list(product_list)),
        challenger=_StubChallenger(list(product_list)),
        source="deterministic_stub",
        meta=meta,
        model_path=None,
    )


def _scores_from_challenger(
    model: Any,
    X: pd.DataFrame,
    product_list: list[str],
) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        raw = np.asarray(model.predict_proba(X), dtype=float)
        return _align_score_columns(raw, _model_catalog(model, product_list), product_list)
    if hasattr(model, "predict_proba_topn"):
        rows = model.predict_proba_topn(X, top_n=len(product_list))
        return _scores_from_rank_rows(rows, product_list)
    if isinstance(model, dict):
        return _scores_from_mapping(model, X, product_list)
    raise TypeError("Challenger model must expose predict_proba, predict_proba_topn, or score dict.")


def _scores_from_champion(
    model: Any,
    X: pd.DataFrame,
    product_list: list[str],
    cutoff_quarter: str,
    events: pd.DataFrame,
) -> np.ndarray:
    if hasattr(model, "rank"):
        X_rank = X.copy()
        owned = owned_products_from_events(X_rank[ENTITY_KEYS], cutoff_quarter, events=events)
        if isinstance(owned, dict):
            X_rank["owned_products"] = X_rank["client_id"].astype(str).map(owned).apply(
                lambda value: value if isinstance(value, list) else []
            )
        rows = []
        for _, row in X_rank.iterrows():
            ranked = model.rank(row, top_n=None)
            rows.append(ranked)
        return _scores_from_rank_rows(rows, product_list)
    if hasattr(model, "predict_proba"):
        raw = np.asarray(model.predict_proba(X), dtype=float)
        return _align_score_columns(raw, _model_catalog(model, product_list), product_list)
    if isinstance(model, dict):
        return _scores_from_mapping(model, X, product_list)
    raise TypeError("Champion model must expose rank, predict_proba, or score dict.")


def _metric_suite(
    Y_true: np.ndarray,
    scores: np.ndarray,
    product_list: list[str],
    k: int,
) -> dict[str, Any]:
    auc_values, auc_macro = per_product_auc(Y_true, scores, product_list)
    return {
        "precision_at_10": precision_at_k(Y_true, scores, k),
        "recall_at_10": recall_at_k(Y_true, scores, k),
        "map_at_10": map_at_k(Y_true, scores, k),
        "ndcg_at_10": ndcg_at_k(Y_true, scores, k),
        "hit_rate_at_10": hit_rate_at_k(Y_true, scores, k),
        "per_product_auc_macro": auc_macro,
        "per_product_auc": auc_values,
        "n_auc_products": int(sum(value is not None for value in auc_values.values())),
    }


def _uplift(
    challenger_metrics: dict[str, Any],
    champion_metrics: dict[str, Any],
) -> dict[str, float]:
    precision_delta = (
        float(challenger_metrics["precision_at_10"])
        - float(champion_metrics["precision_at_10"])
    )
    hit_delta = (
        float(challenger_metrics["hit_rate_at_10"])
        - float(champion_metrics["hit_rate_at_10"])
    )
    return {
        "precision_at_10": precision_delta,
        "hit_rate_at_10": hit_delta,
        "precision_at_10_relative": _relative_delta(
            float(challenger_metrics["precision_at_10"]),
            float(champion_metrics["precision_at_10"]),
        ),
        "hit_rate_at_10_relative": _relative_delta(
            float(challenger_metrics["hit_rate_at_10"]),
            float(champion_metrics["hit_rate_at_10"]),
        ),
    }


def _relative_delta(new: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0
    return float((new - baseline) / baseline)


def _segment_breakdown(
    segments: pd.Series,
    Y_true: np.ndarray,
    scores: np.ndarray,
    k: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment in sorted(set(segments.astype(str))):
        mask = segments.astype(str).eq(segment).to_numpy()
        if not np.any(mask):
            continue
        rows.append(
            {
                "segment": segment,
                "n_clients": int(mask.sum()),
                "hit_rate_at_10": hit_rate_at_k(Y_true[mask], scores[mask], k),
            }
        )
    return rows


def _render_markdown(
    result: dict[str, Any],
    segment_rows: list[dict[str, Any]],
    meta: dict[str, Any],
) -> str:
    generated_at = str(result["generated_at"])
    challenger = result["challenger"]
    champion = result["champion"]
    uplift = result["uplift_vs_popularity"]
    precision_signal = "above" if uplift["precision_at_10"] >= 0 else "below"
    min_support = meta.get("min_support", "unknown")
    source = result.get("model_source", "unknown")

    lines = [
        f"Generated at: {generated_at}",
        "",
        "# NBO offline metric report",
        "",
        f"- holdout_quarter: `{result['holdout_quarter']}`",
        f"- k: `{result['k']}`",
        f"- n_clients_eval: `{result['n_clients_eval']}`",
        f"- n_products: `{result['n_products']}`",
        f"- model_source: `{source}`",
        "",
        "## challenger vs champion",
        "",
        "| metric | challenger | champion | uplift_abs |",
        "|---|---:|---:|---:|",
    ]
    for metric in [
        "precision_at_10",
        "recall_at_10",
        "map_at_10",
        "ndcg_at_10",
        "hit_rate_at_10",
        "per_product_auc_macro",
    ]:
        lines.append(
            "| "
            f"{metric} | {_fmt(challenger.get(metric))} | "
            f"{_fmt(champion.get(metric))} | "
            f"{_fmt(_metric_delta(challenger.get(metric), champion.get(metric)))} |"
        )

    lines.extend(
        [
            "",
            "## uplift",
            "",
            f"- precision_at_10_abs: `{_fmt(uplift['precision_at_10'])}`",
            f"- hit_rate_at_10_abs: `{_fmt(uplift['hit_rate_at_10'])}`",
            "- policy: b04 writes absolute deltas only; b07 owns gate threshold.",
            "",
            "## coverage",
            "",
            f"- scorable_share: `{_fmt(result['scorable_share'])}`",
            f"- not_scorable_share: `{_fmt(result['not_scorable_share'])}`",
            "- no-INN / NOT_SCORABLE rows are excluded from quality metric denominators.",
            "",
            "## denominators",
            "",
            "- precision@10 / hit-rate@10: all scorable rows with non-empty scores.",
            "- recall@10 / MAP@10 / NDCG@10: scorable rows with at least one positive holdout label.",
            "- per-product ROC-AUC: only products with both classes in holdout; one-class products are `null` in JSON.",
            "",
            "## calibration",
            "",
            f"- calibration_gap: `{_fmt(result.get('calibration_gap'))}`",
            "",
            "## per-segment hit-rate@10",
            "",
            "| segment | n_clients | hit_rate_at_10 |",
            "|---|---:|---:|",
        ]
    )
    if segment_rows:
        for row in segment_rows:
            lines.append(
                f"| {row['segment']} | {row['n_clients']} | {_fmt(row['hit_rate_at_10'])} |"
            )
    else:
        lines.append("| none | 0 | n/a |")

    lines.extend(
        [
            "",
            "## notes",
            "",
            f"- min_support: `{min_support}`; small product support can make per-product AUC noisy.",
            f"- auc_products_used: `{challenger.get('n_auc_products', 0)}`.",
            "",
            (
                f"**Вывод:** challenger precision@10 is {precision_signal} champion; "
                "b05/b07 should read `metric_report.json` and apply downstream gate policy."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _metric_delta(value: Any, baseline: Any) -> float | None:
    if value is None or baseline is None:
        return None
    return float(value) - float(baseline)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.6f}"


def _aligned_arrays(Y_true: np.ndarray | pd.DataFrame, scores: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    y = _as_label_matrix(Y_true)
    s = _as_score_matrix(scores)
    if y.shape != s.shape:
        raise ValueError(f"Y_true and scores must have the same shape; got {y.shape} and {s.shape}.")
    return y, s


def _as_label_matrix(value: np.ndarray | pd.DataFrame) -> np.ndarray:
    if isinstance(value, pd.DataFrame):
        cols = [col for col in value.columns if col not in ENTITY_KEYS]
        return value[cols].to_numpy(dtype=int)
    arr = np.asarray(value, dtype=int)
    if arr.ndim != 2:
        raise ValueError("Y_true must be a 2D matrix.")
    return arr


def _as_score_matrix(value: np.ndarray) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 2:
        raise ValueError("scores must be a 2D matrix.")
    return arr


def _hits_at_order(y: np.ndarray, order: np.ndarray) -> np.ndarray:
    if order.shape[1] == 0:
        return np.zeros((y.shape[0], 0), dtype=int)
    return np.take_along_axis(y, order, axis=1)


def _product_names(
    Y_true: np.ndarray | pd.DataFrame,
    product_list: list[str] | None,
) -> list[str]:
    if product_list is not None:
        return list(product_list)
    if isinstance(Y_true, pd.DataFrame):
        return [str(col) for col in Y_true.columns if col not in ENTITY_KEYS]
    width = np.asarray(Y_true).shape[1]
    return [f"PROD_{idx:02d}" for idx in range(1, width + 1)]


def _scorable_mask(scores: np.ndarray, client_status: pd.Series | None = None) -> np.ndarray:
    matrix = _as_score_matrix(scores)
    finite = np.isfinite(matrix).any(axis=1)
    if client_status is None:
        return finite
    status = client_status.reset_index(drop=True).astype(str).str.upper()
    if len(status) != len(finite):
        raise ValueError("client_status length must match score rows.")
    status_ok = status.isin(SCORABLE_STATUSES) | ~status.isin(NOT_SCORABLE_STATUSES)
    return finite & status_ok.to_numpy()


def _align_score_columns(
    scores: np.ndarray,
    model_catalog: list[str],
    product_list: list[str],
) -> np.ndarray:
    matrix = _as_score_matrix(scores)
    if matrix.shape[1] == len(product_list) and model_catalog == product_list:
        return np.clip(matrix, 0.0, 1.0)
    if matrix.shape[1] != len(model_catalog):
        raise ValueError(
            "Model score width does not match model catalog: "
            f"{matrix.shape[1]} vs {len(model_catalog)}."
        )
    out = np.full((matrix.shape[0], len(product_list)), np.nan, dtype=float)
    model_pos = {product: idx for idx, product in enumerate(model_catalog)}
    for out_idx, product in enumerate(product_list):
        if product in model_pos:
            out[:, out_idx] = matrix[:, model_pos[product]]
    return np.clip(out, 0.0, 1.0)


def _scores_from_rank_rows(rows: list[Any], product_list: list[str]) -> np.ndarray:
    out = np.full((len(rows), len(product_list)), np.nan, dtype=float)
    product_pos = {product: idx for idx, product in enumerate(product_list)}
    for row_idx, ranked in enumerate(rows):
        if isinstance(ranked, dict):
            items = ranked.items()
        else:
            items = ranked
        for item in items:
            product, score = item[0], item[1]
            if product in product_pos:
                out[row_idx, product_pos[product]] = float(score)
    return np.clip(out, 0.0, 1.0)


def _scores_from_mapping(
    mapping: dict[str, Any],
    X: pd.DataFrame,
    product_list: list[str],
) -> np.ndarray:
    scores = np.asarray([float(mapping.get(product, 0.0)) for product in product_list])
    return np.tile(scores, (len(X), 1))


def _model_catalog(model: Any, fallback: list[str]) -> list[str]:
    catalog = getattr(model, "catalog", None)
    if catalog is None:
        return list(fallback)
    return [str(product) for product in catalog]


def _resolve_product_catalog(model_dir: Path) -> list[str]:
    meta = _read_model_meta(model_dir)
    for key in ("product_catalog", "catalog"):
        values = meta.get(key)
        if values:
            return [str(value) for value in values]

    catalog_path = model_dir / CATALOG_FILE
    if catalog_path.is_file():
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        values = data.get("product_catalog") or data.get("catalog")
        if values:
            return [str(value) for value in values]

    train_run = _read_train_run()
    values = train_run.get("product_catalog")
    if values:
        return [str(value) for value in values]

    events = load_events()
    return sorted(str(value) for value in events["product"].dropna().unique())


def _catalog_from_labels(labels_all: pd.DataFrame, reference_quarter: str) -> list[str]:
    train = labels_all.loc[
        labels_all["quarter"].map(quarter_index) <= quarter_index(reference_quarter)
    ]
    positives = train.loc[train["y"].eq(1), "product"]
    if positives.empty:
        return sorted(str(value) for value in labels_all["product"].dropna().unique())
    return sorted(str(value) for value in positives.dropna().unique())


def _default_holdout_quarter(events: pd.DataFrame) -> str:
    train_run = _read_train_run()
    holdout = train_run.get("holdout_quarter")
    if holdout:
        return _format_quarter(holdout)
    if events.empty or "ts" not in events.columns:
        raise ValueError("Cannot infer holdout quarter from empty events.")
    max_quarter = _format_quarter(pd.to_datetime(events["ts"]).max())
    return _previous_quarter(max_quarter)


def _previous_quarter(quarter: str) -> str:
    idx = quarter_index(quarter) - 1
    if idx < 0:
        raise ValueError("Holdout quarter has no previous quarter.")
    return quarter_from_index(idx)


def _format_quarter(value: Any) -> str:
    if isinstance(value, pd.Period):
        period = value.asfreq("Q-DEC")
        return f"{period.year}Q{period.quarter}"
    if isinstance(value, pd.Timestamp):
        period = value.to_period("Q-DEC")
        return f"{period.year}Q{period.quarter}"
    text = str(value).strip().upper()
    if "Q" in text:
        year, quarter = text.split("Q", 1)
        quarter = quarter[:1]
        return f"{int(year):04d}Q{int(quarter)}"
    period = pd.Timestamp(text).to_period("Q-DEC")
    return f"{period.year}Q{period.quarter}"


def _build_feature_matrix(
    entities: pd.DataFrame,
    feature_names: list[str],
    events: pd.DataFrame,
) -> pd.DataFrame:
    del events
    parts: list[pd.DataFrame] = []
    for quarter, group in entities.groupby("quarter", sort=True):
        matrix = features.get_features(group[ENTITY_KEYS], str(quarter))
        _ensure_columns(matrix, feature_names)
        parts.append(matrix[ENTITY_KEYS + feature_names])
    if not parts:
        return pd.DataFrame(columns=ENTITY_KEYS + feature_names)
    out = pd.concat(parts, ignore_index=True)
    order = entities.assign(_order=np.arange(len(entities)))
    out = order.merge(out, on=ENTITY_KEYS, how="left").sort_values("_order")
    return out.drop(columns=["_order"]).reset_index(drop=True)


def _entities_from_labels(labels: pd.DataFrame) -> pd.DataFrame:
    entities = labels[ENTITY_KEYS].drop_duplicates().copy()
    entities["_q_idx"] = entities["quarter"].map(quarter_index)
    entities = entities.sort_values(["_q_idx", "client_id"]).drop(columns=["_q_idx"])
    return entities.reset_index(drop=True)


def _align_y(wide: pd.DataFrame, X: pd.DataFrame, catalog: list[str]) -> pd.DataFrame:
    aligned = X[ENTITY_KEYS].merge(wide, on=ENTITY_KEYS, how="left")
    for product in catalog:
        aligned[product] = aligned[product].fillna(0).astype("int8")
    return aligned[ENTITY_KEYS + list(catalog)]


def _client_status(client_ids: pd.Series) -> pd.Series:
    try:
        registry = load_scoring_registry()
    except Exception:
        return pd.Series("SCORABLE", index=client_ids.index, dtype="string")
    if "client_id" not in registry.columns or "scoring_status" not in registry.columns:
        return pd.Series("SCORABLE", index=client_ids.index, dtype="string")
    status_map = (
        registry.drop_duplicates("client_id")
        .set_index("client_id")["scoring_status"]
        .astype(str)
        .to_dict()
    )
    values = client_ids.astype(str).map(status_map).fillna("SCORABLE")
    return values.reset_index(drop=True).astype("string")


def _segments_from_features(X: pd.DataFrame) -> pd.Series:
    segments = []
    for _, row in X.iterrows():
        found = "SEG_UNKNOWN"
        for idx in range(7):
            name = f"seg_SEG_{idx}"
            if name in row and int(row[name]) == 1:
                found = f"SEG_{idx}"
                break
        segments.append(found)
    return pd.Series(segments, dtype="string")


def _read_feature_list() -> dict[str, Any]:
    if not FEATURE_LIST_PATH.is_file():
        raise FileNotFoundError(
            f"feature_list.json not found at {FEATURE_LIST_PATH}; run b02 first."
        )
    return json.loads(FEATURE_LIST_PATH.read_text(encoding="utf-8"))


def _feature_names(feature_list: dict[str, Any]) -> list[str]:
    items = feature_list.get("features", [])
    names = [item["name"] if isinstance(item, dict) else str(item) for item in items]
    if not names:
        raise ValueError("feature_list.json does not contain features.")
    return names


def _check_feature_list(feature_list: dict[str, Any]) -> None:
    names = _feature_names(feature_list)
    missing = [name for name in names if name not in features.FEATURE_COLUMNS]
    if missing:
        raise ValueError(f"feature_list contains unknown b02 features: {missing}")


def _check_model_feature_parity(meta: dict[str, Any], feature_list: dict[str, Any]) -> None:
    expected = meta.get("feature_list_hash")
    if not expected:
        return
    actual = feature_list_hash(feature_list)
    if str(expected) != str(actual):
        raise ValueError(
            "Feature parity failed: model feature_list_hash "
            f"{expected} != current {actual}."
        )


def _read_model_meta(model_dir: Path) -> dict[str, Any]:
    path = model_dir / META_FILE
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _read_train_run() -> dict[str, Any]:
    path = REPORTS_DIR / TRAIN_RUN_FILE
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _ensure_columns(data: pd.DataFrame, columns: list[str]) -> None:
    missing = [name for name in columns if name not in data.columns]
    if missing:
        raise ValueError(f"Feature matrix is missing columns: {missing}")


def _model_dir(value: str | Path | None) -> Path:
    raw = value if value is not None else os.environ.get("MODEL_DIR", str(MODEL_DIR))
    path = Path(os.path.expandvars(str(raw))).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _reports_dir(value: str | Path | None) -> Path:
    raw = value if value is not None else os.environ.get("REPORTS_DIR", str(REPORTS_DIR))
    path = Path(os.path.expandvars(str(raw))).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
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


def _generated_at() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _json_ready(value: Any) -> Any:
    if isinstance(value, np.floating):
        return round(float(value), 6)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, float):
        if np.isnan(value) or np.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


if __name__ == "__main__":
    main()
