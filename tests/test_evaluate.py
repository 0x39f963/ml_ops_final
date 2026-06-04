"""Tests for offline NBO evaluation metrics and reports."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import evaluate, train


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_ranking_metrics_match_manual_values() -> None:
    y_true = np.asarray(
        [
            [1, 0, 1, 0],
            [0, 1, 0, 0],
            [0, 0, 0, 0],
        ]
    )
    scores = np.asarray(
        [
            [0.9, 0.8, 0.7, 0.1],
            [0.4, 0.5, 0.3, 0.2],
            [0.9, 0.8, 0.7, 0.6],
        ]
    )

    expected_ndcg = ((1.0 / (1.0 + 1.0 / math.log2(3))) + 1.0) / 2.0

    assert evaluate.precision_at_k(y_true, scores, 2) == 1.0 / 3.0
    assert evaluate.recall_at_k(y_true, scores, 2) == 0.75
    assert evaluate.map_at_k(y_true, scores, 2) == 0.75
    assert evaluate.ndcg_at_k(y_true, scores, 2) == expected_ndcg
    assert evaluate.hit_rate_at_k(y_true, scores, 2) == 2.0 / 3.0


def test_top_k_tie_break_prefers_lower_product_index() -> None:
    scores = np.asarray([[0.5, 0.5, 0.2, 0.5]])

    order = evaluate.top_k_indices(scores, k=3)

    assert order.tolist() == [[0, 1, 3]]


def test_per_product_auc_skips_one_class_products() -> None:
    y_true = pd.DataFrame(
        {
            "client_id": ["C1", "C2", "C3", "C4"],
            "quarter": ["2022Q1"] * 4,
            "PROD_01": [0, 1, 0, 1],
            "PROD_02": [1, 1, 1, 1],
        }
    )
    scores = np.asarray(
        [
            [0.1, 0.3],
            [0.9, 0.4],
            [0.2, 0.5],
            [0.8, 0.6],
        ]
    )

    aucs, macro = evaluate.per_product_auc(y_true, scores)

    assert aucs["PROD_01"] == 1.0
    assert aucs["PROD_02"] is None
    assert macro == 1.0


def test_coverage_marks_empty_scores_and_not_scorable_rows() -> None:
    scores = np.asarray(
        [
            [0.1, 0.2],
            [np.nan, np.nan],
            [0.3, 0.4],
        ]
    )
    status = pd.Series(["SCORABLE", "SCORABLE", "NOT_SCORABLE"])

    result = evaluate.coverage(scores, status)

    assert result["n_scorable"] == 1
    assert result["n_not_scorable"] == 2
    assert result["scorable_share"] == 1.0 / 3.0
    assert result["not_scorable_share"] == 2.0 / 3.0


def test_evaluate_smoke_writes_contract_reports(tmp_path, monkeypatch) -> None:
    model_dir = tmp_path / "models"
    reports_dir = tmp_path / "reports"
    model_dir.mkdir()
    catalog = ["PROD_01", "PROD_02", "PROD_03", "PROD_04"]
    feature_list = json.loads(
        (PROJECT_ROOT / "artifacts" / "feature_list.json").read_text(encoding="utf-8")
    )
    feature_names = [item["name"] for item in feature_list["features"]]

    champion = train.ChampionModel(
        catalog=catalog,
        global_scores={
            "PROD_01": 0.40,
            "PROD_02": 0.30,
            "PROD_03": 0.20,
            "PROD_04": 0.10,
        },
        segment_scores={},
        co_scores={},
    )
    challenger = train.ChallengerModel(
        backend="logreg",
        catalog=catalog,
        feature_names=feature_names,
        estimator=None,
        variable_products=[],
        constants={
            "PROD_01": 0.10,
            "PROD_02": 0.20,
            "PROD_03": 0.30,
            "PROD_04": 0.40,
        },
    )
    joblib.dump(
        {"champion": champion, "challenger": challenger, "active": "champion"},
        model_dir / "model.pkl",
    )
    (model_dir / "meta.json").write_text(
        json.dumps(
            {
                "feature_list_hash": train.feature_list_hash(feature_list),
                "feature_list": feature_list,
                "product_catalog": catalog,
                "min_support": 1,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EVENTS_PARQUET", str(PROJECT_ROOT / "data" / "sample_synth.parquet"))
    monkeypatch.delenv("DATA_DIR", raising=False)

    result = evaluate.evaluate(
        "2022Q1",
        reports_dir=reports_dir,
        model_dir=model_dir,
    )
    stored = json.loads((reports_dir / "metric_report.json").read_text(encoding="utf-8"))
    md = (reports_dir / "metric_report.md").read_text(encoding="utf-8")

    required = {
        "precision_at_10",
        "recall_at_10",
        "map_at_10",
        "ndcg_at_10",
        "hit_rate_at_10",
        "uplift_vs_popularity",
    }
    assert required <= set(stored)
    assert result["holdout_quarter"] == "2022Q1"
    assert (reports_dir / "metric_report.json").is_file()
    assert (reports_dir / "metric_report.md").is_file()
    assert "challenger vs champion" in md
    assert "**Вывод:**" in md
    assert "scorable_share" in md

    for key in [
        "precision_at_10",
        "recall_at_10",
        "map_at_10",
        "ndcg_at_10",
        "hit_rate_at_10",
        "scorable_share",
    ]:
        assert 0.0 <= float(stored[key]) <= 1.0
    assert {"precision_at_10", "hit_rate_at_10"} <= set(stored["uplift_vs_popularity"])


def test_holdout_loader_keeps_only_requested_quarter(monkeypatch) -> None:
    monkeypatch.setenv("EVENTS_PARQUET", str(PROJECT_ROOT / "data" / "sample_synth.parquet"))
    monkeypatch.delenv("DATA_DIR", raising=False)

    _, y_true = evaluate.load_holdout("2022Q1")

    assert set(y_true["quarter"].astype(str)) == {"2022Q1"}
