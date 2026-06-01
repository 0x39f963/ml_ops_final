# Generated at: 2026-06-01 13:00:25 MSK
"""Build data drift reports for NBO batches.

The public contract for Airflow is:
from monitoring.evidently.drift_report import build_drift_report
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


DRIFT_SHARE_THRESHOLD = 0.20
PSI_WARNING = 0.10
PSI_CRITICAL = 0.25
TEXTFILE_PATH = Path("reports") / "prometheus" / "nbo_drift.prom"


def build_drift_report(
    reference_df: pd.DataFrame,
    current_df: pd.DataFrame,
    score_col: str | None,
    target_cols: list[str] | None,
    out_html: str,
) -> dict[str, Any]:
    """Build a drift report and return a compact summary."""
    reference = _clean_frame(reference_df)
    current = _clean_frame(current_df)
    if reference.empty:
        raise ValueError("reference_df is empty")
    if current.empty:
        raise ValueError("current_df is empty")

    targets = [item for item in (target_cols or []) if item in reference.columns and item in current.columns]
    features = _feature_columns(reference, current, targets)
    if not features:
        raise ValueError("reference_df and current_df have no common feature columns")

    rows = [_column_drift(reference[col], current[col], col) for col in features]
    drifted = [row for row in rows if row["drifted"]]
    numeric_psi = [row["score"] for row in rows if row["method"] == "psi"]
    psi_max = float(max(numeric_psi)) if numeric_psi else 0.0
    drift_share = float(len(drifted) / len(rows))
    generated_at = _utc_stamp()

    score_summary = _score_summary(reference, current, score_col)
    target_summary = [_column_drift(reference[col], current[col], col) for col in targets]

    summary: dict[str, Any] = {
        "dataset_drift": bool(drift_share >= DRIFT_SHARE_THRESHOLD),
        "drift_share": drift_share,
        "n_drifted_features": int(len(drifted)),
        "psi_max": psi_max,
        "generated_at": generated_at,
        "n_features": int(len(rows)),
        "score_col": score_col if score_col in reference.columns and score_col in current.columns else None,
        "target_cols": targets,
    }

    out_path = Path(out_html)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    evident = _try_evidently_report(reference, current, score_col, targets, out_path)
    _append_or_write_html(out_path, summary, rows, score_summary, target_summary, evident)
    return summary


def write_textfile_metrics(summary: dict[str, Any], out_path: str | Path = TEXTFILE_PATH) -> Path:
    """Write drift metrics in Prometheus textfile collector format."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset_drift = 1 if bool(summary.get("dataset_drift")) else 0
    drift_share = float(summary.get("drift_share", 0.0) or 0.0)
    psi_max = float(summary.get("psi_max", 0.0) or 0.0)
    generated_ts = int(datetime.now(timezone.utc).timestamp())
    text = (
        "# HELP nbo_drift_share Share of drifted feature columns in the latest NBO drift run.\n"
        "# TYPE nbo_drift_share gauge\n"
        f"nbo_drift_share {drift_share:.10f}\n"
        "# HELP nbo_dataset_drift Dataset drift flag from the latest NBO drift run.\n"
        "# TYPE nbo_dataset_drift gauge\n"
        f"nbo_dataset_drift {dataset_drift}\n"
        "# HELP nbo_psi_max Maximum numeric PSI from the latest NBO drift run.\n"
        "# TYPE nbo_psi_max gauge\n"
        f"nbo_psi_max {psi_max:.10f}\n"
        "# HELP nbo_drift_generated_timestamp_seconds UTC timestamp of the latest NBO drift run.\n"
        "# TYPE nbo_drift_generated_timestamp_seconds gauge\n"
        f"nbo_drift_generated_timestamp_seconds {generated_ts}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path


def main() -> None:
    args = _parse_args()
    reference = _read_table(args.reference)
    current = _read_table(args.current)
    out = args.out or _default_out_path()
    target_cols = _parse_target_cols(args.target_cols)

    summary = build_drift_report(
        reference,
        current,
        score_col=args.score_col,
        target_cols=target_cols,
        out_html=out,
    )

    if args.push:
        print(
            "warning: --push is accepted for CLI compatibility, but b08 uses node_exporter textfile metrics",
            file=sys.stderr,
        )

    if not args.no_textfile:
        metrics_path = write_textfile_metrics(summary, args.textfile_out)
        summary["textfile_metrics"] = str(metrics_path)

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an NBO drift report.")
    parser.add_argument("--reference", required=True, help="Reference table path: parquet, csv, or json.")
    parser.add_argument("--current", required=True, help="Current table path: parquet, csv, or json.")
    parser.add_argument("--out", default=None, help="Output HTML path. Default: reports/evidently_drift_<UTC>.html")
    parser.add_argument("--score-col", default=None, help="Optional score column for distribution summary.")
    parser.add_argument("--target-cols", nargs="*", default=None, help="Optional target columns for target drift.")
    parser.add_argument("--textfile-out", default=str(TEXTFILE_PATH), help="Prometheus textfile output path.")
    parser.add_argument("--no-textfile", action="store_true", help="Skip writing node_exporter textfile metrics.")
    parser.add_argument("--push", action="store_true", help="Accepted for compatibility; textfile metrics are used here.")
    return parser.parse_args()


def _read_table(path: str) -> pd.DataFrame:
    item = Path(path)
    if not item.is_file():
        raise FileNotFoundError(f"table not found: {item}")
    suffix = item.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(item)
    if suffix == ".csv":
        return pd.read_csv(item)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(item, lines=suffix == ".jsonl")
    raise ValueError(f"unsupported table format: {item.suffix}")


def _clean_frame(data: pd.DataFrame) -> pd.DataFrame:
    out = data.copy()
    out.columns = [str(col) for col in out.columns]
    return out


def _feature_columns(reference: pd.DataFrame, current: pd.DataFrame, targets: list[str]) -> list[str]:
    skip = set(targets)
    common = [col for col in reference.columns if col in current.columns and col not in skip]
    return [col for col in common if not (reference[col].isna().all() and current[col].isna().all())]


def _column_drift(reference: pd.Series, current: pd.Series, name: str) -> dict[str, Any]:
    if _is_numeric(reference) and _is_numeric(current):
        score = _psi(reference, current)
        return {
            "column": name,
            "method": "psi",
            "score": float(score),
            "drifted": bool(score >= PSI_CRITICAL),
        }
    score = _total_variation(reference, current)
    return {
        "column": name,
        "method": "tvd",
        "score": float(score),
        "drifted": bool(score >= DRIFT_SHARE_THRESHOLD),
    }


def _is_numeric(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series)


def _psi(reference: pd.Series, current: pd.Series) -> float:
    ref = pd.to_numeric(reference, errors="coerce").dropna().astype(float)
    cur = pd.to_numeric(current, errors="coerce").dropna().astype(float)
    if ref.empty or cur.empty:
        return 0.0

    if ref.nunique(dropna=True) <= 1:
        bins = np.array([-np.inf, float(ref.iloc[0]), np.inf])
    else:
        quantiles = np.linspace(0.0, 1.0, 11)
        edges = np.unique(np.quantile(ref, quantiles))
        if len(edges) < 3:
            low = min(float(ref.min()), float(cur.min())) - 1e-6
            high = max(float(ref.max()), float(cur.max())) + 1e-6
            edges = np.array([low, high])
        bins = np.concatenate(([-np.inf], edges[1:-1], [np.inf]))

    ref_counts = pd.cut(ref, bins=bins, include_lowest=True).value_counts(sort=False)
    cur_counts = pd.cut(cur, bins=bins, include_lowest=True).value_counts(sort=False)
    ref_rate = ref_counts / max(int(ref_counts.sum()), 1)
    cur_rate = cur_counts / max(int(cur_counts.sum()), 1)
    ref_rate = ref_rate.replace(0, 1e-6)
    cur_rate = cur_rate.replace(0, 1e-6)
    value = ((cur_rate - ref_rate) * np.log(cur_rate / ref_rate)).sum()
    if not math.isfinite(float(value)):
        return 0.0
    return float(max(value, 0.0))


def _total_variation(reference: pd.Series, current: pd.Series) -> float:
    ref = reference.astype("string").fillna("__missing__")
    cur = current.astype("string").fillna("__missing__")
    ref_rate = ref.value_counts(normalize=True)
    cur_rate = cur.value_counts(normalize=True)
    keys = ref_rate.index.union(cur_rate.index)
    ref_aligned = ref_rate.reindex(keys, fill_value=0.0)
    cur_aligned = cur_rate.reindex(keys, fill_value=0.0)
    return float(0.5 * (cur_aligned - ref_aligned).abs().sum())


def _score_summary(reference: pd.DataFrame, current: pd.DataFrame, score_col: str | None) -> dict[str, Any] | None:
    if not score_col or score_col not in reference.columns or score_col not in current.columns:
        return None
    return {
        "reference": _numeric_summary(reference[score_col]),
        "current": _numeric_summary(current[score_col]),
    }


def _numeric_summary(series: pd.Series) -> dict[str, float | None]:
    values = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    if values.empty:
        return {"count": 0.0, "mean": None, "std": None, "p50": None, "p90": None}
    return {
        "count": float(len(values)),
        "mean": float(values.mean()),
        "std": float(values.std(ddof=0)),
        "p50": float(values.quantile(0.50)),
        "p90": float(values.quantile(0.90)),
    }


def _try_evidently_report(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    score_col: str | None,
    target_cols: list[str],
    out_path: Path,
) -> dict[str, Any]:
    try:
        from evidently.metric_preset import DataDriftPreset, TargetDriftPreset
        from evidently.report import Report
    except Exception as exc:
        return {"status": "fallback", "reason": f"evidently import unavailable: {exc}"}

    metrics: list[Any] = [DataDriftPreset()]
    if target_cols:
        metrics.append(TargetDriftPreset())

    try:
        report = Report(metrics=metrics)
        column_mapping = _column_mapping(score_col, target_cols)
        if column_mapping is None:
            report.run(reference_data=reference, current_data=current)
        else:
            report.run(reference_data=reference, current_data=current, column_mapping=column_mapping)
        report.save_html(str(out_path))
        return {"status": "evidently_html", "version": _evidently_version()}
    except Exception as exc:
        return {"status": "fallback", "reason": f"evidently run failed: {exc}"}


def _column_mapping(score_col: str | None, target_cols: list[str]) -> Any | None:
    try:
        from evidently.pipeline.column_mapping import ColumnMapping
    except Exception:
        return None

    mapping = ColumnMapping()
    if score_col:
        mapping.prediction = score_col
    if target_cols:
        mapping.target = target_cols[0]
    return mapping


def _evidently_version() -> str:
    try:
        import evidently

        return str(getattr(evidently, "__version__", "unknown"))
    except Exception:
        return "unavailable"


def _append_or_write_html(
    out_path: Path,
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    score_summary: dict[str, Any] | None,
    target_summary: list[dict[str, Any]],
    evident: dict[str, Any],
) -> None:
    block = _manual_html_block(summary, rows, score_summary, target_summary, evident)
    if out_path.is_file() and evident.get("status") == "evidently_html":
        text = out_path.read_text(encoding="utf-8", errors="ignore")
        if "</body>" in text:
            text = text.replace("</body>", f"{block}</body>")
        else:
            text += block
        out_path.write_text(text, encoding="utf-8")
        return

    html_text = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>NBO drift report</title>"
        "<style>body{font-family:Arial,sans-serif;margin:32px;line-height:1.45}"
        "table{border-collapse:collapse;margin-top:16px}td,th{border:1px solid #ccc;padding:6px 8px}"
        "th{background:#f5f5f5}</style></head><body>"
        "<h1>NBO drift report</h1>"
        f"{block}</body></html>"
    )
    out_path.write_text(html_text, encoding="utf-8")


def _manual_html_block(
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    score_summary: dict[str, Any] | None,
    target_summary: list[dict[str, Any]],
    evident: dict[str, Any],
) -> str:
    summary_rows = "".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in summary.items()
    )
    drift_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['column']))}</td>"
        f"<td>{html.escape(str(row['method']))}</td>"
        f"<td>{float(row['score']):.6f}</td>"
        f"<td>{html.escape(str(row['drifted']))}</td>"
        "</tr>"
        for row in sorted(rows, key=lambda item: item["score"], reverse=True)
    )
    target_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['column']))}</td>"
        f"<td>{html.escape(str(row['method']))}</td>"
        f"<td>{float(row['score']):.6f}</td>"
        f"<td>{html.escape(str(row['drifted']))}</td>"
        "</tr>"
        for row in target_summary
    )
    score_block = _score_html(score_summary)
    evident_note = html.escape(json.dumps(evident, ensure_ascii=False, sort_keys=True))
    return (
        "<section><h2>Summary</h2>"
        f"<table>{summary_rows}</table>"
        f"<p>Evidently status: <code>{evident_note}</code></p>"
        "<h2>Feature drift</h2>"
        "<table><tr><th>column</th><th>method</th><th>score</th><th>drifted</th></tr>"
        f"{drift_rows}</table>"
        f"{score_block}"
        "<h2>Target drift</h2>"
        "<p>Target drift is skipped unless target columns are passed and present in both tables.</p>"
        "<table><tr><th>column</th><th>method</th><th>score</th><th>drifted</th></tr>"
        f"{target_rows}</table></section>"
    )


def _score_html(score_summary: dict[str, Any] | None) -> str:
    if not score_summary:
        return "<h2>Score distribution</h2><p>Score column was not provided or is absent.</p>"
    rows = []
    for side, stats in score_summary.items():
        for key, value in stats.items():
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(side))}</td>"
                f"<td>{html.escape(str(key))}</td>"
                f"<td>{html.escape(str(value))}</td>"
                "</tr>"
            )
    return "<h2>Score distribution</h2><table><tr><th>table</th><th>metric</th><th>value</th></tr>" + "".join(rows) + "</table>"


def _parse_target_cols(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    cols: list[str] = []
    for value in values:
        cols.extend(item.strip() for item in str(value).split(",") if item.strip())
    return cols


def _default_out_path() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return str(Path("reports") / f"evidently_drift_{stamp}.html")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    main()
