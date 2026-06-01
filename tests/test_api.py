# Generated at: 2026-06-01 07:30:04 MSK
"""Smoke tests for the FastAPI NBO scoring contract."""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import serve_api
from src.data_wrappers import load_scoring_registry


class DummyTopNModel:
    catalog = [f"PROD_{idx:02d}" for idx in range(1, 40)]

    def predict_proba(self, X):
        base = np.linspace(0.95, 0.05, len(self.catalog), dtype=float)
        return np.tile(base, (len(X), 1))


class MarkerModel:
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.catalog = ["PROD_01"]

    def predict_proba(self, X):
        p = 0.9 if self.marker == "champion" else 0.1
        return np.full((len(X), 1), p, dtype=float)


def _scorable_client() -> str:
    registry = load_scoring_registry()
    return str(registry.loc[registry["scoring_status"].eq("SCORABLE"), "client_id"].iloc[0])


def _install_dummy_state(monkeypatch) -> None:
    def fake_load_model() -> None:
        feature_list = serve_api._read_feature_list()
        serve_api.STATE.update(
            {
                "model": DummyTopNModel(),
                "model_kind": "test_dummy",
                "version": "test-v1",
                "feature_list_hash": feature_list["hash"],
                "metrics": {"precision_at_10": 0.12},
                "data_cutoff": "2026Q1",
                "alias": "champion",
                "loaded_at": "2026-06-01 07:30:04 MSK",
                "model_name": "nbo_topn_test",
                "product_catalog": DummyTopNModel.catalog,
                "feature_names": [item["name"] for item in feature_list["features"]],
                "feature_list": feature_list,
                "scoring_registry": serve_api._load_population_registry(),
                "product_family_map": serve_api._load_product_family_map(),
                "last_error": None,
            }
        )

    monkeypatch.setenv("TOP_N", "10")
    monkeypatch.setenv("SCORE_DECISION_THRESHOLD", "0.5")
    monkeypatch.setenv("MODEL_REFRESH_ON_REQUEST", "false")
    monkeypatch.setattr(serve_api, "load_model", fake_load_model)


def test_health_ok(monkeypatch) -> None:
    _install_dummy_state(monkeypatch)
    with TestClient(serve_api.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["champion_alias"] == "champion"
    assert body["data_cutoff"] == "2026Q1"


def test_score_valid_shape(monkeypatch) -> None:
    _install_dummy_state(monkeypatch)
    client_id = _scorable_client()
    with TestClient(serve_api.app) as client:
        response = client.post(
            "/score",
            json={"client_id": client_id, "reference_date": "2026Q1"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["client_id"] == client_id
    assert body["status"] == "scorable"
    assert body["model_version"] == "test-v1"
    assert body["segment_id"] in {None, *serve_api.PUBLIC_SEGMENTS}
    assert len(body["score"]) == 10
    assert body["recommended_action"].startswith("offer top product PROD_")
    assert any("propensity proxy only" in item for item in body["caveats"])
    assert any("cutoff = latest completed quarter" in item for item in body["caveats"])
    for item in body["score"]:
        assert item["product"].startswith("PROD_")
        assert 0.0 <= item["p"] <= 1.0
        assert item["decision"] in {"recommend", "hold"}
        assert item["confidence"] in {"high", "medium", "low"}


def test_score_not_scorable_honest(monkeypatch) -> None:
    _install_dummy_state(monkeypatch)
    with TestClient(serve_api.app) as client:
        response = client.post(
            "/score",
            json={"client_id": "C_NOT_IN_POPULATION", "reference_date": "2026Q1"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_scorable"
    assert body["score"] is None
    assert body["recommended_action"] == "no scoring: client not in scorable population"
    assert not any(item.get("product") for item in body.get("score") or [])


def test_model_info(monkeypatch) -> None:
    _install_dummy_state(monkeypatch)
    with TestClient(serve_api.app) as client:
        response = client.get("/model-info")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "test-v1"
    assert body["feature_list_hash"]
    assert body["metrics"]["precision_at_10"] == 0.12


def test_metrics_prometheus(monkeypatch) -> None:
    _install_dummy_state(monkeypatch)
    with TestClient(serve_api.app) as client:
        client.get("/health")
        client.post(
            "/score",
            json={"client_id": _scorable_client(), "reference_date": "2026Q1"},
        )
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    text = response.text
    assert "nbo_requests_total" in text
    assert "nbo_request_latency_seconds_bucket" in text
    assert "nbo_score_distribution_bucket" in text


def test_batch_score(monkeypatch) -> None:
    _install_dummy_state(monkeypatch)
    with TestClient(serve_api.app) as client:
        response = client.post(
            "/batch-score",
            json={
                "client_ids": [_scorable_client(), "C_NOT_IN_POPULATION"],
                "reference_date": "2026Q1",
                "top_n": 5,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["status"] == "scorable"
    assert len(body[0]["score"]) == 5
    assert body[1]["status"] == "not_scorable"
    assert body[1]["score"] is None


def test_local_bundle_loads_champion(tmp_path, monkeypatch) -> None:
    feature_list = serve_api._read_feature_list()
    model_path = tmp_path / "model.pkl"
    joblib.dump(
        {
            "champion": MarkerModel("champion"),
            "challenger": MarkerModel("challenger"),
            "active": "champion",
        },
        model_path,
    )

    monkeypatch.setattr(serve_api, "_load_mlflow_model", lambda model_name: None)
    monkeypatch.setattr(serve_api, "_load_population_registry", lambda: None)
    monkeypatch.setattr(serve_api, "_load_product_family_map", lambda: {})
    monkeypatch.setattr(
        serve_api.registry,
        "get_champion",
        lambda model_name: {
            "version": "bundle-v1",
            "run_id": "run-bundle-v1",
            "feature_list_hash": feature_list["hash"],
            "metrics": {"precision_at_10": 0.1},
            "alias": "champion",
            "data_cutoff": "2026Q1",
            "model_path": str(model_path),
        },
    )

    serve_api.load_model()

    assert serve_api.STATE["model_kind"] == "local_joblib_champion"
    assert serve_api.STATE["version"] == "bundle-v1"
    assert serve_api.STATE["model"].marker == "champion"


def test_local_single_model_loads_as_joblib(tmp_path) -> None:
    model_path = tmp_path / "model.pkl"
    joblib.dump(MarkerModel("single"), model_path)

    model, model_kind = serve_api._load_local_model(
        str(model_path),
        local_hash="hash-not-used-for-tagged-path",
    )

    assert model_kind == "local_joblib"
    assert model.marker == "single"
