"""Data access wrappers for local real data with synthetic fallback."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd


SYNTH_PATH = Path(__file__).resolve().parents[1] / "data" / "sample_synth.parquet"
DEFAULT_EVENTS_NAME = "enriched_event_table.parquet"
DEFAULT_SEGMENT_TIMELINE_NAME = "segment_timeline.parquet"
DEFAULT_SCORING_REGISTRY_NAME = "scoring_registry.parquet"


def normalize_client_id(value) -> str:
    """Return a stable public client_id string without whitespace."""
    if value is None:
        return ""
    return "".join(str(value).strip().split())


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def _real_path(env_name: str, default_name: str) -> Path | None:
    direct_path = os.environ.get(env_name)
    if direct_path:
        path = _expand_path(direct_path)
        if path.is_file():
            return path

    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        path = _expand_path(data_dir) / default_name
        if path.is_file():
            return path

    return None


def _load_synth_events() -> pd.DataFrame:
    if not SYNTH_PATH.is_file():
        raise FileNotFoundError(
            "Synthetic event parquet was not found. Run `make data` "
            "to generate data/sample_synth.parquet."
        )
    return pd.read_parquet(SYNTH_PATH)


def _filter_cutoff(data: pd.DataFrame, cutoff: str | None) -> pd.DataFrame:
    if cutoff is None:
        return data

    if "ts" not in data.columns:
        raise ValueError("Event data must contain a ts column for cutoff filter.")

    cutoff_ts = pd.to_datetime(cutoff)
    data = data.copy()
    data["ts"] = pd.to_datetime(data["ts"])
    return data.loc[data["ts"] <= cutoff_ts].reset_index(drop=True)


def load_events(cutoff: str | None = None) -> pd.DataFrame:
    """Load event data from local env path or the synthetic stub."""
    source = _real_path("EVENTS_PARQUET", DEFAULT_EVENTS_NAME)
    if source is None:
        source = SYNTH_PATH

    if not source.is_file():
        raise FileNotFoundError(
            "Event parquet was not found. Set EVENTS_PARQUET/DATA_DIR "
            "or run `make data` to generate data/sample_synth.parquet."
        )

    data = pd.read_parquet(source)
    return _filter_cutoff(data, cutoff)


def load_segment_timeline(cutoff: str | None = None) -> pd.DataFrame:
    """Load segment timeline or derive a public synthetic fallback."""
    source = _real_path("SEGMENT_TIMELINE_PARQUET", DEFAULT_SEGMENT_TIMELINE_NAME)
    if source is not None:
        data = pd.read_parquet(source)
        return _filter_cutoff(data, cutoff) if "ts" in data.columns else data

    events = _filter_cutoff(_load_synth_events(), cutoff)
    timeline = (
        events.sort_values("ts")
        .drop_duplicates(["client_id", "year", "quarter"], keep="last")
        [["client_id", "year", "quarter", "segment"]]
        .reset_index(drop=True)
    )
    period = (
        timeline["year"].astype(str)
        + "Q"
        + timeline["quarter"].astype(str)
    )
    timeline["reference_date"] = pd.PeriodIndex(period, freq="Q").end_time
    return timeline[
        ["client_id", "year", "quarter", "reference_date", "segment"]
    ]


def load_scoring_registry() -> pd.DataFrame:
    """Load scoring registry or derive a public synthetic fallback."""
    source = _real_path("SCORING_REGISTRY_PARQUET", DEFAULT_SCORING_REGISTRY_NAME)
    if source is not None:
        return pd.read_parquet(source)

    events = _load_synth_events()
    registry = (
        events.groupby("client_id", dropna=False)
        .agg(
            event_count=("product", "size"),
            inn_is_pseudo=("inn_is_pseudo", "max"),
            last_ts=("ts", "max"),
        )
        .reset_index()
    )
    registry["scoring_status"] = _registry_status(registry)
    return registry[
        ["client_id", "scoring_status", "event_count", "inn_is_pseudo", "last_ts"]
    ]


def _registry_status(registry: pd.DataFrame) -> pd.Series:
    no_client = registry["client_id"].eq("")
    pseudo = registry["inn_is_pseudo"].astype(bool)
    low_evidence = registry["event_count"].lt(2)
    status = pd.Series("SCORABLE", index=registry.index, dtype="object")
    status.loc[low_evidence] = "LOW_EVIDENCE"
    status.loc[pseudo] = "PROVISIONAL"
    status.loc[no_client] = "NOT_SCORABLE"
    return status
