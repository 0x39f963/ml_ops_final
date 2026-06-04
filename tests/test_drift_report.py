"""Smoke tests for the b08 drift report contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from monitoring.evidently.drift_report import build_drift_report, write_textfile_metrics


def test_build_drift_report_writes_html_and_summary(tmp_path) -> None:
    data = pd.DataFrame(
        {
            "client_id": ["C001", "C002", "C003", "C004"],
            "score": [0.1, 0.2, 0.3, 0.4],
            "feature_num": [1.0, 2.0, 3.0, 4.0],
            "segment": ["SEG_0", "SEG_1", "SEG_0", "SEG_1"],
            "target": [0, 1, 0, 1],
        }
    )
    out_html = tmp_path / "drift.html"

    summary = build_drift_report(
        data,
        data.copy(),
        score_col="score",
        target_cols=["target"],
        out_html=str(out_html),
    )

    assert out_html.is_file()
    assert summary["drift_share"] == 0.0
    assert summary["n_drifted_features"] == 0
    assert "generated_at" in summary
    assert "drift_share" in out_html.read_text(encoding="utf-8")


def test_write_textfile_metrics(tmp_path) -> None:
    out = tmp_path / "nbo_drift.prom"
    write_textfile_metrics(
        {
            "dataset_drift": True,
            "drift_share": 0.4,
            "psi_max": 0.3,
        },
        out,
    )

    text = out.read_text(encoding="utf-8")
    assert "nbo_drift_share 0.4000000000" in text
    assert "nbo_dataset_drift 1" in text
    assert "nbo_psi_max 0.3000000000" in text
