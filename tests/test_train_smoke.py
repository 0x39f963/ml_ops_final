# Generated at: 2026-05-31 21:53:25 MSK
"""Smoke tests for NBO training on the synthetic stub."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import labels, train


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_next_quarter_year_boundary() -> None:
    assert labels.next_quarter("2024Q3") == "2024Q4"
    assert labels.next_quarter("2024Q4") == "2025Q1"


def test_build_labels_long_contract() -> None:
    events = pd.DataFrame(
        [
            {
                "client_id": "C1",
                "ts": "2024-01-15",
                "product": "PROD_01",
                "lifecycle_role": "primary",
                "inn_is_pseudo": False,
            },
            {
                "client_id": "C1",
                "ts": "2024-04-15",
                "product": "PROD_01",
                "lifecycle_role": "renewal",
                "inn_is_pseudo": False,
            },
            {
                "client_id": "C2",
                "ts": "2024-04-15",
                "product": "PROD_02",
                "lifecycle_role": "special",
                "inn_is_pseudo": False,
            },
            {
                "client_id": "C3",
                "ts": "2024-04-15",
                "product": "PROD_03",
                "lifecycle_role": "primary",
                "inn_is_pseudo": True,
            },
        ]
    )

    out = labels.build_labels("2024Q1", events=events)

    assert list(out.columns) == labels.LABEL_COLUMNS
    assert set(out["product"]) == {"PROD_01"}
    assert out.loc[
        out["client_id"].eq("C1")
        & out["quarter"].eq("2024Q1")
        & out["product"].eq("PROD_01"),
        "y",
    ].iloc[0] == 1
    assert "C2" not in set(out["client_id"])
    assert "C3" not in set(out["client_id"])


def test_feature_list_hash_uses_schema_token() -> None:
    feature_list = json.loads(
        (PROJECT_ROOT / "artifacts" / "feature_list.json").read_text(encoding="utf-8")
    )
    changed = dict(feature_list)
    changed["generated_at"] = "2099-01-01 00:00:00 MSK"

    fallback = {
        "generated_at": feature_list["generated_at"],
        "features": feature_list["features"],
    }
    fallback_changed = dict(fallback)
    fallback_changed["generated_at"] = "2099-01-01 00:00:00 MSK"

    assert train.feature_list_hash(feature_list) == feature_list["hash"]
    assert train.feature_list_hash(changed) == feature_list["hash"]
    assert train.feature_list_hash(fallback) == train.feature_list_hash(fallback_changed)


def test_owned_products_from_events_activates_co_occurrence() -> None:
    events = pd.DataFrame(
        [
            {
                "client_id": "C1",
                "ts": "2024-01-15",
                "product": "PROD_02",
                "lifecycle_role": "primary",
                "inn_is_pseudo": False,
            },
            {
                "client_id": "C1",
                "ts": "2024-02-15",
                "product": "PROD_01",
                "lifecycle_role": "special",
                "inn_is_pseudo": False,
            },
            {
                "client_id": "C1",
                "ts": "2024-07-15",
                "product": "PROD_03",
                "lifecycle_role": "primary",
                "inn_is_pseudo": False,
            },
            {
                "client_id": "C2",
                "ts": "2024-01-15",
                "product": "PROD_03",
                "lifecycle_role": "primary",
                "inn_is_pseudo": True,
            },
        ]
    )
    champion = train.ChampionModel(
        catalog=["PROD_01", "PROD_02", "PROD_03"],
        global_scores={"PROD_01": 0.2, "PROD_02": 0.05, "PROD_03": 0.1},
        segment_scores={
            "SEG_0": {"PROD_01": 0.2, "PROD_02": 0.05, "PROD_03": 0.1}
        },
        co_scores={"PROD_02": {"PROD_01": 0.0, "PROD_03": 0.95}},
        co_weight=0.9,
    )

    owned = train.owned_products_from_events("C1", "2024Q1", events=events)
    batch_owned = train.owned_products_from_events(
        pd.DataFrame({"client_id": ["C1", "C2"]}),
        "2024Q1",
        events=events,
    )
    base = champion.rank({"seg_SEG_0": 1}, top_n=3)
    with_owned = champion.rank({"seg_SEG_0": 1, "owned_products": owned}, top_n=3)

    assert owned == ["PROD_02"]
    assert batch_owned == {"C1": ["PROD_02"], "C2": []}
    assert base[0][0] == "PROD_01"
    assert with_owned[0][0] == "PROD_03"


def test_train_smoke_creates_artifacts_and_is_deterministic(tmp_path, monkeypatch) -> None:
    model_dir = tmp_path / "models"
    sample = PROJECT_ROOT / "data" / "sample_synth.parquet"
    monkeypatch.setenv("EVENTS_PARQUET", str(sample))
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setenv("MODEL_DIR", str(model_dir))
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "")

    result_1 = train.train_model(
        "2021Q4",
        backend="logreg",
        min_support=50,
        seed=42,
        model_dir=model_dir,
    )
    meta_1 = json.loads(Path(result_1["meta_path"]).read_text(encoding="utf-8"))

    result_2 = train.train_model(
        "2021Q4",
        backend="logreg",
        min_support=50,
        seed=42,
        model_dir=model_dir,
    )
    meta_2 = json.loads(Path(result_2["meta_path"]).read_text(encoding="utf-8"))

    required_meta = {
        "created_at",
        "feature_list_hash",
        "feature_list",
        "product_catalog",
        "seed",
        "backend",
        "min_support",
        "metrics",
        "lib_versions",
    }
    required_metrics = {
        "n_train_rows",
        "n_holdout_rows",
        "n_products_catalog",
        "macro_auc_challenger",
        "seed",
        "backend",
        "min_support",
    }

    assert Path(result_1["model_path"]).is_file()
    assert Path(result_1["meta_path"]).is_file()
    assert required_meta <= set(meta_1)
    assert required_metrics <= set(meta_1["metrics"])
    assert meta_1["feature_list_hash"]
    assert meta_1["feature_list_hash"] == meta_1["feature_list"]["hash"]
    assert meta_1["product_catalog"]
    assert meta_1["feature_list_hash"] == meta_2["feature_list_hash"]
    assert meta_1["product_catalog"] == meta_2["product_catalog"]

    artifact = joblib.load(result_2["model_path"])
    assert sorted(artifact) == ["active", "challenger", "champion"]
    assert artifact["active"] == "champion"
    assert artifact["champion"].rank({"seg_SEG_0": 1}, top_n=3)

    feature_names = artifact["challenger"].feature_names
    X = pd.DataFrame([{name: 0 for name in feature_names}])
    topn = artifact["challenger"].predict_proba_topn(X, top_n=3)
    assert len(topn) == 1
    assert len(topn[0]) == 3
