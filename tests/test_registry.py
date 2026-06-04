"""Smoke tests for MLflow registry alias switching."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
from sklearn.dummy import DummyClassifier


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import registry


def test_registry_alias_promote_and_rollback(tmp_path, monkeypatch) -> None:
    store = tmp_path / "mlruns"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"file:{store}")
    monkeypatch.setenv("MLFLOW_MODEL_NAME", "nbo_topn_test")
    module = importlib.reload(registry)

    X = pd.DataFrame({"x": [0, 1, 2, 3]})
    y_v1 = [0, 0, 1, 1]
    y_v2 = [0, 1, 1, 1]
    model_v1 = DummyClassifier(strategy="prior").fit(X, y_v1)
    model_v2 = DummyClassifier(strategy="most_frequent").fit(X, y_v2)

    run_v1 = module.log_run(
        params={"kind": "baseline", "data_cutoff": "2022Q1"},
        metrics={"precision_at_10": 0.10, "map_at_10": 0.05},
        model=model_v1,
        feature_list_hash="hash-v1",
        model_role=module.CHAMPION_ALIAS,
        run_name="registry-test-v1",
    )
    version_v1 = module.register_model_version(
        str(run_v1),
        tags={"feature_list_hash": "hash-v1", "data_cutoff": "2022Q1"},
    )
    assert module.register_model_version(str(run_v1)) == version_v1
    module.set_alias(module.CHAMPION_ALIAS, version_v1)

    run_v2 = module.log_run(
        params={"kind": "supervised", "data_cutoff": "2022Q1"},
        metrics={"precision_at_10": 0.12, "map_at_10": 0.07},
        model=model_v2,
        feature_list_hash="hash-v2",
        model_role=module.CHALLENGER_ALIAS,
        run_name="registry-test-v2",
    )
    version_v2 = module.register_model_version(
        str(run_v2),
        tags={"feature_list_hash": "hash-v2", "data_cutoff": "2022Q1"},
    )
    module.set_alias(module.CHALLENGER_ALIAS, version_v2)

    promoted = module.promote(version_v2)
    champion = module.get_champion()
    challenger = module.get_challenger()

    assert promoted == {
        "model": "nbo_topn_test",
        "champion": version_v2,
        "previous": version_v1,
    }
    assert champion["version"] == version_v2
    assert champion["run_id"] == run_v2
    assert champion["feature_list_hash"] == "hash-v2"
    assert champion["metrics"]["precision_at_10"] == 0.12
    assert challenger["version"] == version_v2

    restored = module.rollback()
    assert restored == {
        "model": "nbo_topn_test",
        "champion": version_v1,
        "rolled_back_from": version_v2,
    }
    assert module.get_champion()["version"] == version_v1
    assert module.get_model_info()["champion_version"] == version_v1


def test_register_metadata_only_version_with_local_model_path(tmp_path, monkeypatch) -> None:
    store = tmp_path / "mlruns"
    model_file = tmp_path / "model.pkl"
    model_file.write_text("local-only pointer", encoding="utf-8")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"file:{store}")
    monkeypatch.setenv("MLFLOW_MODEL_NAME", "nbo_topn_pointer_test")
    module = importlib.reload(registry)

    run_id = module.log_run(
        params={"kind": "real_train", "model_path": str(model_file)},
        metrics={"macro_auc_challenger": 0.8},
        feature_list_hash="hash-real",
        model_role=module.CHALLENGER_ALIAS,
        run_name="registry-pointer-test",
    )
    version = module.register_model_version(
        str(run_id),
        tags={"feature_list_hash": "hash-real", "model_path": str(model_file)},
        source_uri=model_file.resolve().as_uri(),
    )
    module.set_alias(module.CHALLENGER_ALIAS, version)

    info = module.get_challenger()
    assert info["version"] == version
    assert info["feature_list_hash"] == "hash-real"
    assert info["model_path"] == str(model_file)
    assert info["metrics"]["macro_auc_challenger"] == 0.8
