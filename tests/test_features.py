# Generated at: 2026-05-31 21:21:30 MSK
"""Tests for parity-safe feature build."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import features


def _event_frame(rows: list[dict]) -> pd.DataFrame:
    data = pd.DataFrame(rows)
    data["ts"] = pd.to_datetime(data["ts"])
    cols = [
        "client_id",
        "ts",
        "quarter",
        "product",
        "product_family",
        "segment",
        "lifecycle_role",
    ]
    if "revenue_proxy" in data.columns:
        cols.append("revenue_proxy")
    return data[cols]


def _base_events() -> pd.DataFrame:
    return _event_frame(
        [
            {
                "client_id": "C1",
                "ts": "2025-01-15",
                "quarter": 1,
                "product": "PROD_01",
                "product_family": "software_box",
                "segment": "SEG_2",
                "lifecycle_role": "primary",
            },
            {
                "client_id": "C1",
                "ts": "2025-04-10",
                "quarter": 2,
                "product": "PROD_02",
                "product_family": "software_cloud",
                "segment": "SEG_3",
                "lifecycle_role": "renewal",
            },
            {
                "client_id": "C2",
                "ts": "2024-12-20",
                "quarter": 4,
                "product": "PROD_31",
                "product_family": "FAM_DEVICE",
                "segment": "SEG_1",
                "lifecycle_role": "replacement",
            },
        ]
    )


def test_build_returns_matrix() -> None:
    matrix = features.build_features(
        [("C1", "2025Q2"), ("C_NEW", "2025Q2")],
        features.quarter_to_cutoff_end("2025Q2"),
        events=_base_events(),
    )

    assert not matrix.empty
    assert list(matrix.columns) == features.ENTITY_KEYS + features.FEATURE_COLUMNS
    assert matrix.set_index(features.ENTITY_KEYS).index.is_unique
    assert str(matrix["seg_SEG_0"].dtype) == "int8"
    assert str(matrix["freq_events_total"].dtype) == "int64"


def test_feature_list_stable() -> None:
    matrix_a = features.build_features(
        [("C1", "2025Q2"), ("C2", "2025Q2")],
        features.quarter_to_cutoff_end("2025Q2"),
        events=_base_events(),
    )
    matrix_b = features.build_features(
        [("C3", "2025Q2")],
        features.quarter_to_cutoff_end("2025Q2"),
        events=_event_frame(
            [
                {
                    "client_id": "C3",
                    "ts": "2025-03-01",
                    "quarter": 1,
                    "product": "PROD_35",
                    "product_family": "addon",
                    "segment": "SEG_6",
                    "lifecycle_role": "migration",
                }
            ]
        ),
    )

    info_a = features.compute_feature_list(matrix_a)
    info_b = features.compute_feature_list(matrix_b)

    assert info_a["hash"] == info_b["hash"]
    assert info_a["features"] == info_b["features"]


def test_pit_assert_passes() -> None:
    events = _event_frame(
        [
            {
                "client_id": "C1",
                "ts": "2025-04-01",
                "quarter": 2,
                "product": "PROD_01",
                "product_family": "software_box",
                "segment": "SEG_1",
                "lifecycle_role": "primary",
            },
            {
                "client_id": "C1",
                "ts": "2025-07-01",
                "quarter": 3,
                "product": "PROD_02",
                "product_family": "software_cloud",
                "segment": "SEG_4",
                "lifecycle_role": "primary",
            },
        ]
    )

    matrix = features.build_features(
        [("C1", "2025Q2")],
        features.quarter_to_cutoff_end("2025Q2"),
        events=events,
    )

    row = matrix.iloc[0]
    assert row["freq_events_total"] == 1
    assert row["affinity_fam_software_box"] == 1
    assert row["affinity_fam_software_cloud"] == 0
    assert row["seg_SEG_1"] == 1
    assert row["seg_SEG_4"] == 0


def test_pit_assert_rejects_unfiltered_future_rows() -> None:
    events = _event_frame(
        [
            {
                "client_id": "C1",
                "ts": "2025-07-01",
                "quarter": 3,
                "product": "PROD_02",
                "product_family": "software_cloud",
                "segment": "SEG_4",
                "lifecycle_role": "primary",
            }
        ]
    )

    with pytest.raises(AssertionError, match="PIT violation"):
        features._assert_pit(events, features.quarter_to_cutoff_end("2025Q2"))


def test_monetary_proxy_counts_non_null_money_events() -> None:
    events = _event_frame(
        [
            {
                "client_id": "C1",
                "ts": "2025-01-10",
                "quarter": 1,
                "product": "PROD_01",
                "product_family": "software_box",
                "segment": "SEG_1",
                "lifecycle_role": "primary",
                "revenue_proxy": 100.0,
            },
            {
                "client_id": "C1",
                "ts": "2025-02-10",
                "quarter": 1,
                "product": "PROD_02",
                "product_family": "software_box",
                "segment": "SEG_1",
                "lifecycle_role": "renewal",
                "revenue_proxy": None,
            },
            {
                "client_id": "C1",
                "ts": "2025-03-10",
                "quarter": 1,
                "product": "PROD_03",
                "product_family": "addon",
                "segment": "SEG_1",
                "lifecycle_role": "special",
                "revenue_proxy": 200.0,
            },
            {
                "client_id": "C1",
                "ts": "2025-04-10",
                "quarter": 2,
                "product": "PROD_04",
                "product_family": "software_cloud",
                "segment": "SEG_1",
                "lifecycle_role": "migration",
                "revenue_proxy": None,
            },
        ]
    )

    matrix = features.build_features(
        [("C1", "2025Q2")],
        features.quarter_to_cutoff_end("2025Q2"),
        events=events,
    )
    row = matrix.iloc[0]
    assert row["freq_events_total"] == 3
    assert row["monetary_proxy_count"] == 2
    assert row["monetary_proxy_count"] != row["freq_events_total"]

    without_money_col = events.drop(columns=["revenue_proxy"])
    fallback = features.build_features(
        [("C1", "2025Q2")],
        features.quarter_to_cutoff_end("2025Q2"),
        events=without_money_col,
    )
    assert fallback.iloc[0]["monetary_proxy_count"] == 0


def test_no_future_leak() -> None:
    events = _event_frame(
        [
            {
                "client_id": "C_FUTURE",
                "ts": "2025-07-15",
                "quarter": 3,
                "product": "PROD_01",
                "product_family": "software_box",
                "segment": "SEG_5",
                "lifecycle_role": "primary",
            }
        ]
    )

    matrix = features.build_features(
        [("C_FUTURE", "2025Q2"), ("C_EMPTY", "2025Q2")],
        features.quarter_to_cutoff_end("2025Q2"),
        events=events,
    ).set_index("client_id")

    future_row = matrix.loc["C_FUTURE", features.FEATURE_COLUMNS]
    empty_row = matrix.loc["C_EMPTY", features.FEATURE_COLUMNS]
    pd.testing.assert_series_equal(future_row, empty_row, check_names=False)


def test_column_order_matches_feature_list() -> None:
    matrix = features.build_features(
        [("C1", "2025Q2")],
        features.quarter_to_cutoff_end("2025Q2"),
        events=_base_events(),
    )
    info = features.compute_feature_list(matrix)

    assert [item["name"] for item in info["features"]] == list(
        matrix.columns[len(features.ENTITY_KEYS):]
    )


def test_get_features_parity(tmp_path, monkeypatch) -> None:
    feature_list_path = tmp_path / "feature_list.json"
    store_dir = tmp_path / "feature_store"
    monkeypatch.setattr(features, "FEATURE_LIST_PATH", feature_list_path)
    monkeypatch.setenv("FEATURE_STORE_DIR", str(store_dir))

    matrix = features.build_features(
        [("C1", "2025Q2")],
        features.quarter_to_cutoff_end("2025Q2"),
        events=_base_events(),
    )
    features._write_feature_list(features.compute_feature_list(matrix))

    part_dir = store_dir / "quarter=2025Q2"
    part_dir.mkdir(parents=True)
    shuffled = features.ENTITY_KEYS + list(reversed(features.FEATURE_COLUMNS))
    matrix[shuffled].to_parquet(part_dir / "part.parquet", index=False)

    result = features.get_features([("C1", "2025Q2")], "2025Q2")

    assert list(result.columns) == features.ENTITY_KEYS + features.FEATURE_COLUMNS
