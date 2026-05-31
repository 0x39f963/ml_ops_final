# Generated at: 2026-05-31 21:21:30 MSK
"""Parity-safe feature build and local feature store."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import warnings
from datetime import datetime
from numbers import Integral
from pathlib import Path
from typing import Iterable

import pandas as pd

from .data_wrappers import load_events, normalize_client_id


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FEATURE_LIST_PATH = PROJECT_ROOT / "artifacts" / "feature_list.json"
DEFAULT_FEATURE_STORE_DIR = PROJECT_ROOT / "data" / "feature_store"

ENTITY_KEYS = ["client_id", "quarter"]
SEGMENTS = [f"SEG_{idx}" for idx in range(7)]
CANONICAL_FAMILIES = [
    "software_box",
    "hardware_license",
    "infra",
    "software_cloud",
    "addon",
]
SIGNAL_ROLES = {"primary", "renewal", "replacement", "migration"}
RECENCY_SENTINEL = -1
DSL_SENTINEL = -1

SEGMENT_FEATURES = [f"seg_{segment}" for segment in SEGMENTS]
AFFINITY_FEATURES = [f"affinity_fam_{family}" for family in CANONICAL_FAMILIES]
FEATURE_COLUMNS = [
    *SEGMENT_FEATURES,
    "recency_quarters",
    "freq_events_total",
    "freq_events_last_4q",
    "monetary_proxy_count",
    *AFFINITY_FEATURES,
    "tenure_quarters",
    "dsl_month_lag",
]
FEATURE_DTYPES = {
    **{name: "int8" for name in SEGMENT_FEATURES},
    **{name: "int64" for name in FEATURE_COLUMNS if name not in SEGMENT_FEATURES},
}

REQUIRED_EVENT_COLUMNS = {
    "client_id",
    "ts",
    "quarter",
    "product",
    "product_family",
    "segment",
    "lifecycle_role",
}

_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")
_YYYYQ_INT_RE = re.compile(r"^(\d{4})([1-4])$")
_SYNTH_FAMILY_ALIASES = {
    "fam_box": "software_box",
    "fam_device": "hardware_license",
    "fam_service": "infra",
    "fam_migration": "infra",
    "fam_subscription": "software_cloud",
    "fam_addon": "addon",
}


def quarter_to_cutoff_end(q) -> pd.Timestamp:
    """Return the last nanosecond of a quarter label."""
    return pd.Period(_format_quarter(q), freq="Q-DEC").end_time


def _normalize_entities(entities) -> pd.DataFrame:
    """Normalize supported entity inputs to client_id, quarter rows."""
    if isinstance(entities, pd.DataFrame):
        missing = set(ENTITY_KEYS) - set(entities.columns)
        if missing:
            raise ValueError(f"Entities are missing columns: {sorted(missing)}")
        data = entities[ENTITY_KEYS].copy()
    else:
        items = list(entities)
        if not items:
            data = pd.DataFrame(columns=ENTITY_KEYS)
        elif isinstance(items[0], dict):
            data = pd.DataFrame(items)
            missing = set(ENTITY_KEYS) - set(data.columns)
            if missing:
                raise ValueError(f"Entities are missing columns: {sorted(missing)}")
            data = data[ENTITY_KEYS].copy()
        elif isinstance(items[0], (tuple, list)) and len(items[0]) == 2:
            data = pd.DataFrame(items, columns=ENTITY_KEYS)
        else:
            raise TypeError(
                "Entities must be a DataFrame, list of dicts, "
                "or list of (client_id, quarter) tuples."
            )

    data["client_id"] = data["client_id"].map(normalize_client_id)
    data["quarter"] = data["quarter"].map(_format_quarter)
    return data.drop_duplicates(ENTITY_KEYS).reset_index(drop=True)


def build_features(
    entities,
    cutoff_end: pd.Timestamp,
    events: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a fixed-order PIT feature matrix for one cutoff quarter."""
    cutoff_ts = pd.to_datetime(cutoff_end)
    entity_data = _normalize_entities(entities)
    _check_entity_quarter(entity_data, cutoff_ts)

    event_data = load_events() if events is None else events.copy()
    _validate_events(event_data)
    event_data = _prepare_events(event_data)

    events_pit = event_data.loc[event_data["ts"] <= cutoff_ts].copy()
    _assert_pit(events_pit, cutoff_ts)

    out = _base_feature_frame(entity_data)
    if out.empty or events_pit.empty:
        return _finalize_features(out)

    clients = set(out["client_id"])
    client_events = events_pit.loc[events_pit["client_id"].isin(clients)].copy()
    if client_events.empty:
        return _finalize_features(out)

    signal_events = client_events.loc[
        client_events["lifecycle_role_norm"].isin(SIGNAL_ROLES)
    ].copy()

    _add_segment_features(out, client_events)
    _add_event_lag_features(out, client_events)
    _add_frequency_features(out, signal_events, client_events)
    _add_affinity_features(out, signal_events)
    return _finalize_features(out)


def compute_feature_list(df: pd.DataFrame) -> dict:
    """Return the schema contract for feature columns in matrix order."""
    missing = [name for name in FEATURE_COLUMNS if name not in df.columns]
    if missing:
        raise ValueError(f"Feature matrix is missing columns: {missing}")

    features = [
        {"name": name, "dtype": str(df[name].dtype)}
        for name in FEATURE_COLUMNS
    ]
    schema_payload = json.dumps(
        [(item["name"], item["dtype"]) for item in features],
        ensure_ascii=True,
        sort_keys=False,
        separators=(",", ":"),
    )
    return {
        "version": "1",
        "generated_at": _generated_at(),
        "entity_keys": ENTITY_KEYS,
        "features": features,
        "hash": hashlib.sha256(schema_payload.encode("utf-8")).hexdigest(),
    }


def build_and_store(quarters: list[str]) -> Path:
    """Materialize quarter partitions into the local Parquet feature store."""
    store_dir = _feature_store_dir()
    store_dir.mkdir(parents=True, exist_ok=True)

    events = _prepare_events(load_events())
    last_matrix = None
    for quarter in quarters:
        quarter_label = _format_quarter(quarter)
        cutoff_end = quarter_to_cutoff_end(quarter_label)
        events_pit = events.loc[events["ts"] <= cutoff_end].copy()
        clients = sorted(
            events_pit["client_id"].dropna().map(normalize_client_id).unique()
        )
        entities = pd.DataFrame(
            {"client_id": clients, "quarter": quarter_label},
            columns=ENTITY_KEYS,
        )
        matrix = build_features(entities, cutoff_end, events=events_pit)
        _write_partition(store_dir, quarter_label, matrix)
        last_matrix = matrix

    if last_matrix is None:
        empty = _base_feature_frame(pd.DataFrame(columns=ENTITY_KEYS))
        last_matrix = _finalize_features(empty)
    _write_feature_list(compute_feature_list(last_matrix))
    return store_dir


def get_features(entities, cutoff) -> pd.DataFrame:
    """Read features from store and reindex them by feature_list order."""
    quarter_label = _cutoff_to_quarter(cutoff)
    cutoff_end = quarter_to_cutoff_end(quarter_label)
    entity_data = _normalize_entities(entities)
    _check_entity_quarter(entity_data, cutoff_end)

    feature_list = _read_feature_list()
    feature_names = (
        [item["name"] for item in feature_list["features"]]
        if feature_list is not None
        else FEATURE_COLUMNS
    )

    part_path = _partition_file(_feature_store_dir(), quarter_label)
    if part_path.is_file():
        stored = pd.read_parquet(part_path)
        matrix = _rows_from_store(entity_data, stored, feature_names)
        missing = matrix.loc[matrix[feature_names].isna().all(axis=1), ENTITY_KEYS]
        if not missing.empty:
            built = build_features(missing, cutoff_end)
            matrix = _merge_missing_rows(matrix, built, feature_names)
    else:
        warnings.warn(
            f"Feature store partition {quarter_label} is missing; building on the fly.",
            RuntimeWarning,
            stacklevel=2,
        )
        matrix = build_features(entity_data, cutoff_end)

    if feature_list is None:
        feature_list = compute_feature_list(matrix)
        _write_feature_list(feature_list)
        feature_names = [item["name"] for item in feature_list["features"]]

    _ensure_columns(matrix, feature_names)
    matrix = matrix[ENTITY_KEYS + feature_names].copy()
    return _finalize_features(matrix, feature_names=feature_names)


def _format_quarter(value) -> str:
    if isinstance(value, pd.Period):
        period = value.asfreq("Q-DEC")
        return f"{period.year}Q{period.quarter}"
    if isinstance(value, pd.Timestamp):
        return _timestamp_quarter(value)
    if (
        hasattr(value, "year")
        and hasattr(value, "month")
        and not isinstance(value, str)
    ):
        return _timestamp_quarter(pd.Timestamp(value))

    if isinstance(value, Integral):
        text = str(value)
        int_match = _YYYYQ_INT_RE.match(text)
        if int_match:
            return f"{int_match.group(1)}Q{int_match.group(2)}"
        if value < 0:
            raise ValueError("Integer quarter index must be non-negative.")
        year = 1970 + value // 4
        quarter = value % 4 + 1
        return f"{year}Q{quarter}"

    text = str(value).strip().upper()
    match = _QUARTER_RE.match(text)
    if match:
        return f"{match.group(1)}Q{match.group(2)}"
    try:
        return _timestamp_quarter(pd.Timestamp(text))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Quarter must use YYYYQn, a date-like value, or an integer index."
        ) from exc


def _timestamp_quarter(value: pd.Timestamp) -> str:
    period = value.to_period("Q-DEC")
    return f"{period.year}Q{period.quarter}"


def _cutoff_to_quarter(cutoff) -> str:
    return _format_quarter(cutoff)


def _check_entity_quarter(entity_data: pd.DataFrame, cutoff_end: pd.Timestamp) -> None:
    if entity_data.empty:
        return
    cutoff_quarter = _timestamp_quarter(pd.Timestamp(cutoff_end))
    quarters = set(entity_data["quarter"])
    if quarters != {cutoff_quarter}:
        raise ValueError(
            f"Entities quarter must match cutoff quarter {cutoff_quarter}; "
            f"got {sorted(quarters)}."
        )


def _validate_events(events: pd.DataFrame) -> None:
    missing = sorted(REQUIRED_EVENT_COLUMNS - set(events.columns))
    if missing:
        raise ValueError(f"Event data is missing required columns: {missing}")


def _assert_pit(events_pit: pd.DataFrame, cutoff_ts: pd.Timestamp) -> None:
    max_used_ts = events_pit["ts"].max()
    assert pd.isna(max_used_ts) or max_used_ts <= cutoff_ts, (
        f"PIT violation: {max_used_ts} > {cutoff_ts}"
    )


def _prepare_events(events: pd.DataFrame) -> pd.DataFrame:
    _validate_events(events)
    data = events.copy()
    data["client_id"] = data["client_id"].map(normalize_client_id)
    data["ts"] = pd.to_datetime(data["ts"])
    data["event_q_idx"] = data["ts"].dt.year * 4 + data["ts"].dt.quarter - 1
    data["segment_norm"] = data["segment"].astype("string").str.strip().str.upper()
    data["lifecycle_role_norm"] = (
        data["lifecycle_role"].astype("string").str.strip().str.lower()
    )
    data["family_norm"] = data["product_family"].map(_canonical_family)
    return data


def _canonical_family(value) -> str | None:
    if pd.isna(value):
        return None
    key = str(value).strip().lower()
    if key in CANONICAL_FAMILIES:
        return key
    return _SYNTH_FAMILY_ALIASES.get(key)


def _base_feature_frame(entity_data: pd.DataFrame) -> pd.DataFrame:
    out = entity_data[ENTITY_KEYS].copy()
    for name in SEGMENT_FEATURES:
        out[name] = pd.Series(0, index=out.index, dtype="int8")
    for name in FEATURE_COLUMNS:
        if name in SEGMENT_FEATURES:
            continue
        default = RECENCY_SENTINEL if name == "recency_quarters" else 0
        if name == "dsl_month_lag":
            default = DSL_SENTINEL
        out[name] = pd.Series(default, index=out.index, dtype="int64")
    return out


def _add_segment_features(out: pd.DataFrame, events: pd.DataFrame) -> None:
    last_segment = (
        events.sort_values(["client_id", "ts"])
        .drop_duplicates("client_id", keep="last")
        .set_index("client_id")["segment_norm"]
    )
    for segment in SEGMENTS:
        out[f"seg_{segment}"] = (
            out["client_id"]
            .map(last_segment)
            .eq(segment)
            .fillna(False)
            .astype("int8")
        )


def _add_event_lag_features(out: pd.DataFrame, events: pd.DataFrame) -> None:
    stats = (
        events.groupby("client_id", dropna=False)
        .agg(
            first_q_idx=("event_q_idx", "min"),
            last_q_idx=("event_q_idx", "max"),
            last_ts=("ts", "max"),
        )
    )
    entity_q_idx = out["quarter"].map(_quarter_index).astype("int64")
    first_q_idx = out["client_id"].map(stats["first_q_idx"])
    last_q_idx = out["client_id"].map(stats["last_q_idx"])
    last_ts = out["client_id"].map(stats["last_ts"])

    has_events = last_q_idx.notna()
    out.loc[has_events, "recency_quarters"] = (
        entity_q_idx.loc[has_events] - last_q_idx.loc[has_events].astype("int64")
    ).clip(lower=0)
    out.loc[has_events, "tenure_quarters"] = (
        entity_q_idx.loc[has_events] - first_q_idx.loc[has_events].astype("int64") + 1
    ).clip(lower=0)
    entity_cutoff = pd.to_datetime(
        out.loc[has_events, "quarter"].map(quarter_to_cutoff_end)
    )
    last_seen = pd.to_datetime(last_ts.loc[has_events])
    out.loc[has_events, "dsl_month_lag"] = (
        (entity_cutoff.dt.year - last_seen.dt.year) * 12
        + (entity_cutoff.dt.month - last_seen.dt.month)
    ).clip(lower=0)


def _add_frequency_features(
    out: pd.DataFrame,
    signal_events: pd.DataFrame,
    client_events: pd.DataFrame,
) -> None:
    # Frequency features count signal lifecycle events only.
    if signal_events.empty:
        total = pd.Series(dtype="int64")
    else:
        total = signal_events.groupby("client_id", dropna=False).size()
    out["freq_events_total"] = out["client_id"].map(total).fillna(0).astype("int64")

    if "revenue_proxy" in client_events.columns:
        # The upstream revenue_proxy field is sparse; count presence, not amount.
        money_events = client_events.loc[client_events["revenue_proxy"].notna()]
        money_count = money_events.groupby("client_id", dropna=False).size()
        out["monetary_proxy_count"] = (
            out["client_id"].map(money_count).fillna(0).astype("int64")
        )

    entity_q_idx = out["quarter"].map(_quarter_index).astype("int64")
    last_4 = pd.Series(0, index=out.index, dtype="int64")
    # build_features enforces one quarter per matrix; loop keeps tests flexible.
    for q_idx in sorted(entity_q_idx.unique()):
        row_mask = entity_q_idx.eq(q_idx)
        counts = (
            signal_events.loc[signal_events["event_q_idx"].between(q_idx - 3, q_idx)]
            .groupby("client_id", dropna=False)
            .size()
        )
        last_4.loc[row_mask] = (
            out.loc[row_mask, "client_id"].map(counts).fillna(0).astype("int64")
        )
    out["freq_events_last_4q"] = last_4


def _add_affinity_features(out: pd.DataFrame, events: pd.DataFrame) -> None:
    if events.empty:
        return
    counts = (
        events.loc[events["family_norm"].isin(CANONICAL_FAMILIES)]
        .groupby(["client_id", "family_norm"], dropna=False)
        .size()
        .unstack(fill_value=0)
    )
    for family in CANONICAL_FAMILIES:
        name = f"affinity_fam_{family}"
        if family in counts.columns:
            out[name] = out["client_id"].map(counts[family]).fillna(0).astype("int64")


def _quarter_index(value) -> int:
    label = _format_quarter(value)
    year, quarter = label.split("Q")
    return int(year) * 4 + int(quarter) - 1


def _finalize_features(
    data: pd.DataFrame,
    feature_names: list[str] | None = None,
) -> pd.DataFrame:
    feature_names = FEATURE_COLUMNS if feature_names is None else feature_names
    data = data[ENTITY_KEYS + feature_names].copy()
    data["client_id"] = data["client_id"].astype("string")
    data["quarter"] = data["quarter"].astype("string")
    for name in feature_names:
        dtype = FEATURE_DTYPES.get(name, "int64")
        default = 0
        if name == "recency_quarters":
            default = RECENCY_SENTINEL
        elif name == "dsl_month_lag":
            default = DSL_SENTINEL
        data[name] = data[name].fillna(default).astype(dtype)
    return data


def _generated_at() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _feature_store_dir() -> Path:
    value = os.environ.get("FEATURE_STORE_DIR")
    if not value:
        return DEFAULT_FEATURE_STORE_DIR
    path = Path(os.path.expandvars(value)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _partition_file(store_dir: Path, quarter: str) -> Path:
    return store_dir / f"quarter={quarter}" / "part.parquet"


def _write_partition(store_dir: Path, quarter: str, matrix: pd.DataFrame) -> None:
    part_dir = store_dir / f"quarter={quarter}"
    if part_dir.exists():
        shutil.rmtree(part_dir)
    part_dir.mkdir(parents=True, exist_ok=True)
    matrix.to_parquet(part_dir / "part.parquet", engine="pyarrow", index=False)


def _write_feature_list(info: dict, path: Path | None = None) -> None:
    path = FEATURE_LIST_PATH if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(info, ensure_ascii=True, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(payload)
        temp_name = handle.name
    Path(temp_name).replace(path)


def _read_feature_list(path: Path | None = None) -> dict | None:
    path = FEATURE_LIST_PATH if path is None else path
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _rows_from_store(
    entity_data: pd.DataFrame,
    stored: pd.DataFrame,
    feature_names: list[str],
) -> pd.DataFrame:
    missing = sorted(set(ENTITY_KEYS) - set(stored.columns))
    if missing:
        raise ValueError(f"Feature store partition is missing keys: {missing}")
    _ensure_columns(stored, feature_names)
    stored = stored[ENTITY_KEYS + feature_names].copy()
    return entity_data.merge(stored, on=ENTITY_KEYS, how="left")


def _merge_missing_rows(
    matrix: pd.DataFrame,
    built: pd.DataFrame,
    feature_names: list[str],
) -> pd.DataFrame:
    present = matrix.loc[~matrix[feature_names].isna().all(axis=1), ENTITY_KEYS + feature_names]
    combined = pd.concat([present, built[ENTITY_KEYS + feature_names]], ignore_index=True)
    keys = matrix[ENTITY_KEYS].drop_duplicates()
    return keys.merge(combined, on=ENTITY_KEYS, how="left")


def _ensure_columns(data: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = [name for name in columns if name not in data.columns]
    if missing:
        raise ValueError(f"Missing feature columns: {missing}")
