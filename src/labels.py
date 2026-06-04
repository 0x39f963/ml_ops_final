"""Quarterly multi-label target build for NBO training."""

from __future__ import annotations

import re
from numbers import Integral

import pandas as pd

from .data_wrappers import load_events, normalize_client_id


LABEL_COLUMNS = ["client_id", "quarter", "product", "y"]
ENTITY_KEYS = ["client_id", "quarter"]
POSITIVE_ROLES = {"primary", "renewal", "replacement", "migration"}
NOISE_ROLES = {"test", "special"}

_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")
_YYYYQ_INT_RE = re.compile(r"^(\d{4})([1-4])$")


def next_quarter(q: str) -> str:
    """Return the next YYYYQn quarter label."""
    idx = quarter_index(q) + 1
    return quarter_from_index(idx)


def quarter_index(value) -> int:
    """Convert a quarter label or date-like value to a monotonic quarter index."""
    label = format_quarter(value)
    year, quarter = label.split("Q")
    return int(year) * 4 + int(quarter) - 1


def quarter_from_index(idx: int) -> str:
    """Convert a monotonic quarter index to YYYYQn."""
    if idx < 0:
        raise ValueError("Quarter index must be non-negative.")
    year = idx // 4
    quarter = idx % 4 + 1
    return f"{year}Q{quarter}"


def format_quarter(value) -> str:
    """Normalize supported quarter values to YYYYQn."""
    if isinstance(value, pd.Period):
        period = value.asfreq("Q-DEC")
        return f"{period.year}Q{period.quarter}"
    if isinstance(value, pd.Timestamp):
        return _timestamp_quarter(value)
    if hasattr(value, "year") and hasattr(value, "month") and not isinstance(value, str):
        return _timestamp_quarter(pd.Timestamp(value))

    if isinstance(value, Integral):
        text = str(value)
        int_match = _YYYYQ_INT_RE.match(text)
        if int_match:
            return f"{int_match.group(1)}Q{int_match.group(2)}"
        return quarter_from_index(int(value))

    text = str(value).strip().upper()
    match = _QUARTER_RE.match(text)
    if match:
        return f"{match.group(1)}Q{match.group(2)}"
    try:
        return _timestamp_quarter(pd.Timestamp(text))
    except (TypeError, ValueError) as exc:
        raise ValueError("Quarter must use YYYYQn, a date-like value, or an index.") from exc


def build_labels(
    reference_quarter: str,
    *,
    exclude_special: bool = True,
    events: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build long labels for train quarters through Q_t and holdout Q_t+1.

    The role column is selected as lifecycle_role when present, else event_type.
    Evidence: ML-002 event contract defines both fields; b01 synthetic exposes
    lifecycle_role.
    """
    data = _prepare_events(load_events() if events is None else events)
    if data.empty:
        return _empty_labels()

    max_ref_idx = quarter_index(next_quarter(reference_quarter))
    source = data.loc[data["event_q_idx"] <= max_ref_idx + 1].copy()
    if exclude_special:
        source = source.loc[~source["role_norm"].isin(NOISE_ROLES)].copy()
    source = source.loc[source["product"].notna() & source["product"].ne("")].copy()

    products = sorted(source["product"].unique())
    if not products:
        return _empty_labels()

    first_seen = source.groupby("client_id", dropna=False)["event_q_idx"].min().sort_index()
    if first_seen.empty:
        return _empty_labels()

    positives = (
        source.loc[source["role_norm"].isin(POSITIVE_ROLES), ["client_id", "product", "event_q_idx"]]
        .drop_duplicates()
        .copy()
    )

    parts: list[pd.DataFrame] = []
    min_ref_idx = int(first_seen.min())
    for ref_idx in range(min_ref_idx, max_ref_idx + 1):
        clients = first_seen.index[first_seen <= ref_idx]
        if len(clients) == 0:
            continue

        grid = pd.MultiIndex.from_product(
            [clients, products],
            names=["client_id", "product"],
        ).to_frame(index=False)
        grid["quarter"] = quarter_from_index(ref_idx)

        target = positives.loc[
            positives["event_q_idx"].eq(ref_idx + 1),
            ["client_id", "product"],
        ].drop_duplicates()
        if target.empty:
            grid["y"] = 0
        else:
            target_idx = pd.MultiIndex.from_frame(target)
            grid_idx = pd.MultiIndex.from_frame(grid[["client_id", "product"]])
            grid["y"] = grid_idx.isin(target_idx).astype("int8")
        parts.append(grid[LABEL_COLUMNS])

    if not parts:
        return _empty_labels()
    labels = pd.concat(parts, ignore_index=True)
    labels["client_id"] = labels["client_id"].astype("string")
    labels["quarter"] = labels["quarter"].astype("string")
    labels["product"] = labels["product"].astype("string")
    labels["y"] = labels["y"].astype("int8")
    return labels


def to_wide(labels: pd.DataFrame, catalog: list[str]) -> pd.DataFrame:
    """Convert long labels to a fixed-order wide multi-label matrix."""
    if labels.empty:
        return pd.DataFrame(columns=ENTITY_KEYS + list(catalog))

    wide = labels.pivot_table(
        index=ENTITY_KEYS,
        columns="product",
        values="y",
        aggfunc="max",
        fill_value=0,
    )
    wide = wide.reindex(columns=list(catalog), fill_value=0).astype("int8")
    wide = wide.reset_index()
    wide.columns.name = None
    return wide[ENTITY_KEYS + list(catalog)]


def build_catalog(labels_train: pd.DataFrame, min_support: int) -> list[str]:
    """Return products with train positives >= min_support in stable order."""
    if min_support < 1:
        raise ValueError("min_support must be >= 1.")
    if labels_train.empty:
        return []

    counts = (
        labels_train.loc[labels_train["y"].eq(1)]
        .groupby("product", dropna=False)
        .size()
        .sort_index()
    )
    return [str(product) for product, count in counts.items() if int(count) >= min_support]


def _prepare_events(events: pd.DataFrame) -> pd.DataFrame:
    missing = sorted({"client_id", "ts", "product"} - set(events.columns))
    if missing:
        raise ValueError(f"Event data is missing required columns: {missing}")

    role_col = _role_column(events)
    data = events.copy()
    data["client_id"] = data["client_id"].map(normalize_client_id)
    data = data.loc[data["client_id"].ne("")].copy()
    if "inn_is_pseudo" in data.columns:
        data = data.loc[~_as_bool(data["inn_is_pseudo"])].copy()

    data["ts"] = pd.to_datetime(data["ts"])
    data["event_q_idx"] = data["ts"].dt.year * 4 + data["ts"].dt.quarter - 1
    data["product"] = data["product"].astype("string").str.strip()
    data["role_norm"] = data[role_col].astype("string").str.strip().str.lower()
    data = data.loc[data["product"].notna() & data["product"].ne("")].copy()
    return data.reset_index(drop=True)


def _role_column(events: pd.DataFrame) -> str:
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


def _timestamp_quarter(value: pd.Timestamp) -> str:
    period = value.to_period("Q-DEC")
    return f"{period.year}Q{period.quarter}"


def _empty_labels() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "client_id": pd.Series(dtype="string"),
            "quarter": pd.Series(dtype="string"),
            "product": pd.Series(dtype="string"),
            "y": pd.Series(dtype="int8"),
        },
        columns=LABEL_COLUMNS,
    )
