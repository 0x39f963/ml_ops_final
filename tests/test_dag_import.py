# Generated at: 2026-06-01 09:49:30 MSK
"""Smoke tests for the NBO Airflow DAG module."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def _load_dag_module():
    path = PROJECT_ROOT / "dags" / "nbo_retrain_dag.py"
    spec = importlib.util.spec_from_file_location("nbo_retrain_dag", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_dag_imports_without_airflow_and_has_fixed_task_ids() -> None:
    module = _load_dag_module()

    expected = {
        "wait_for_batch",
        "validate_data",
        "build_features",
        "train",
        "evaluate",
        "compare_with_champion",
        "register_model",
        "skip_deploy",
        "finish",
    }

    assert module.dag.dag_id == "nbo_retrain_pipeline"
    assert set(module.dag.task_ids) == expected
    assert module.dag.catchup is False
    assert module.dag.default_args["retries"] == 1


def test_dag_branch_dependencies_are_fixed() -> None:
    module = _load_dag_module()

    assert module.wait_for_batch.downstream_task_ids == {"validate_data"}
    assert module.validate.downstream_task_ids == {"build_features"}
    assert module.build.downstream_task_ids == {"train"}
    assert module.train.downstream_task_ids == {"evaluate"}
    assert module.evaluate.downstream_task_ids == {"compare_with_champion"}
    assert module.compare.downstream_task_ids == {"register_model", "skip_deploy"}
    assert module.register.downstream_task_ids == {"finish"}
    assert module.skip.downstream_task_ids == {"finish"}


def test_metric_gate_reads_current_b04_report_shape(tmp_path, monkeypatch) -> None:
    module = _load_dag_module()
    report_path = tmp_path / "metric_report.json"
    report_path.write_text(
        json.dumps(
            {
                "challenger": {"precision_at_10": 0.12},
                "champion": {"precision_at_10": 0.10},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "METRIC_REPORT_PATH", report_path)
    monkeypatch.setattr(module, "GATE_THRESHOLD", 0.10)

    assert module.choose_deploy_branch() == "register_model"

    report_path.write_text(
        json.dumps(
            {
                "challenger": {"precision_at_10": 0.09},
                "champion": {"precision_at_10": 0.10},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert module.choose_deploy_branch() == "skip_deploy"
