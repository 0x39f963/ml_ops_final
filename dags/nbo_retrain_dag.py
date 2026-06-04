"""Airflow retraining DAG for the NBO champion/challenger flow."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from airflow import DAG
    from airflow.operators.empty import EmptyOperator
    from airflow.operators.python import BranchPythonOperator, PythonOperator
    from airflow.providers.amazon.aws.hooks.s3 import S3Hook
    from airflow.providers.amazon.aws.sensors.s3 import S3KeySensor
    from airflow.sensors.filesystem import FileSensor
    from airflow.utils.trigger_rule import TriggerRule
except ImportError:
    _CURRENT_DAG = None

    class DAG:
        def __init__(self, *args, **kwargs):
            self.dag_id = kwargs.get("dag_id", args[0] if args else None)
            self.start_date = kwargs.get("start_date")
            self.schedule = kwargs.get("schedule")
            self.catchup = kwargs.get("catchup")
            self.default_args = kwargs.get("default_args", {})
            self.tags = kwargs.get("tags", [])
            self.tasks = []
            self.task_dict = {}

        @property
        def task_ids(self):
            return list(self.task_dict)

        def add_task(self, task):
            if task.task_id not in self.task_dict:
                self.tasks.append(task)
                self.task_dict[task.task_id] = task

        def __enter__(self):
            global _CURRENT_DAG
            _CURRENT_DAG = self
            return self

        def __exit__(self, *args):
            global _CURRENT_DAG
            _CURRENT_DAG = None
            return False

    class _Task:
        def __init__(self, *args, **kwargs):
            self.task_id = kwargs.get("task_id", args[0] if args else self.__class__.__name__)
            self.python_callable = kwargs.get("python_callable")
            self.trigger_rule = kwargs.get("trigger_rule")
            self.downstream_task_ids = set()
            self.upstream_task_ids = set()
            if _CURRENT_DAG is not None:
                _CURRENT_DAG.add_task(self)

        def __rshift__(self, other):
            if isinstance(other, (list, tuple, set)):
                for item in other:
                    self >> item
                return other
            self.downstream_task_ids.add(other.task_id)
            other.upstream_task_ids.add(self.task_id)
            return other

    class EmptyOperator(_Task):
        pass

    class PythonOperator(_Task):
        pass

    class BranchPythonOperator(_Task):
        pass

    class FileSensor(_Task):
        pass

    class S3KeySensor(_Task):
        pass

    class S3Hook:
        def __init__(self, *args, **kwargs):
            pass

        def get_key(self, *args, **kwargs):
            return None

    class TriggerRule:
        NONE_FAILED_MIN_ONE_SUCCESS = "none_failed_min_one_success"

from src import features, registry
from src.evaluate import evaluate as evaluate_model
from src.train import train_model


LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]


def _env_path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, default)).expanduser()
    return path if path.is_absolute() else ROOT / path


USE_S3_SENSOR = os.getenv("NBO_USE_S3_SENSOR", "0") == "1"
LOCAL_BATCH_PATH = _env_path(
    "NBO_BATCH_PATH",
    str(ROOT / "data" / "current_batch.parquet"),
)
S3_BUCKET = os.getenv("NBO_S3_BUCKET", "nbo-batches")
S3_KEY_TEMPLATE = os.getenv("NBO_S3_KEY_TEMPLATE", "incoming/{{ ds }}/events.parquet")
GATE_THRESHOLD = float(os.getenv("NBO_GATE_PRECISION_AT_10_THRESHOLD", "0.10"))
METRIC_REPORT_PATH = _env_path(
    "NBO_METRIC_REPORT",
    str(ROOT / "reports" / "metric_report.json"),
)
MODEL_DIR = _env_path("MODEL_DIR", str(ROOT / "models"))
FEATURE_STORE_DIR = _env_path("FEATURE_STORE_DIR", str(ROOT / "data" / "feature_store"))
DAG_SCHEDULE = os.getenv("NBO_DAG_SCHEDULE", "@daily")
TRAIN_REFERENCE_QUARTER = os.getenv("NBO_TRAIN_REFERENCE_QUARTER", "").strip()
FEATURE_STORE_QUARTERS = os.getenv("NBO_FEATURE_STORE_QUARTERS", "").strip()

PRODUCT_RE = re.compile(r"^PROD_(0[1-9]|[12][0-9]|3[0-9])$")
QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")
SEGMENT_RE = re.compile(r"^SEG_[0-6]$")
ROLE_VALUES = {"primary", "renewal", "replacement", "migration", "test", "special"}
SCORE_COLUMNS = {"score", "p", "probability", "prediction_score", "pred"}


def _resolve_s3_key(context: dict[str, object]) -> str:
    ds = str(context.get("ds") or datetime.utcnow().date().isoformat())
    return S3_KEY_TEMPLATE.replace("{{ ds }}", ds).replace("{ds}", ds)


def _batch_path(context: dict[str, object]) -> Path:
    LOCAL_BATCH_PATH.parent.mkdir(parents=True, exist_ok=True)

    if USE_S3_SENSOR:
        key = _resolve_s3_key(context)
        s3_object = S3Hook(aws_conn_id="aws_default").get_key(
            key=key,
            bucket_name=S3_BUCKET,
        )
        if s3_object is None:
            raise FileNotFoundError(f"s3://{S3_BUCKET}/{key} not found")
        s3_object.download_file(str(LOCAL_BATCH_PATH))
        LOGGER.info("Downloaded S3 batch s3://%s/%s to %s", S3_BUCKET, key, LOCAL_BATCH_PATH)

    if not LOCAL_BATCH_PATH.is_file():
        raise FileNotFoundError(f"NBO batch parquet not found: {LOCAL_BATCH_PATH}")

    _set_runtime_paths(LOCAL_BATCH_PATH)
    return LOCAL_BATCH_PATH


def _set_runtime_paths(batch_path: Path) -> None:
    os.environ["EVENTS_PARQUET"] = str(batch_path)
    os.environ.setdefault("FEATURE_STORE_DIR", str(FEATURE_STORE_DIR))
    os.environ.setdefault("MODEL_DIR", str(MODEL_DIR))


def validate_batch_data(**context: object) -> dict[str, object]:
    path = _batch_path(context)
    data = pd.read_parquet(path)
    errors: list[str] = []

    if data.empty:
        errors.append("batch is empty")

    _check_required_columns(data, errors)
    _check_client_id(data, errors)
    _check_quarter(data, errors)
    _check_product(data, errors)
    _check_role(data, errors)
    _check_segment(data, errors)
    _check_score_ranges(data, errors)

    if errors:
        raise ValueError(f"NBO batch validation failed: {errors}")

    report = {"status": "pass", "n_rows": int(len(data)), "errors": [], "path": str(path)}
    LOGGER.info("NBO batch validation passed: %s", report)
    return report


def build_nbo_features(**context: object) -> dict[str, object]:
    path = _batch_path(context)
    reference_quarter = _reference_quarter(path)
    quarters = _feature_store_quarters(reference_quarter)
    store_path = features.build_and_store(quarters)
    return {
        "status": "built",
        "feature_store": str(store_path),
        "quarters": quarters,
        "reference_quarter": reference_quarter,
        "batch_path": str(path),
    }


def train_nbo_model(**context: object) -> dict[str, object]:
    path = _batch_path(context)
    reference_quarter = _reference_quarter(path)
    result = train_model(reference_quarter, model_dir=MODEL_DIR)
    result["reference_quarter"] = reference_quarter
    result["batch_path"] = str(path)
    LOGGER.info("NBO train finished: run_id=%s version=%s", result.get("run_id"), result.get("mlflow_model_version"))
    return result


def evaluate_nbo_model(**context: object) -> dict[str, object]:
    path = _batch_path(context)
    reference_quarter = _reference_quarter(path)
    holdout_quarter = _next_quarter(reference_quarter)
    report = evaluate_model(
        holdout_quarter,
        reports_dir=METRIC_REPORT_PATH.parent,
        model_dir=MODEL_DIR,
    )
    default_report_path = METRIC_REPORT_PATH.parent / "metric_report.json"
    if default_report_path != METRIC_REPORT_PATH and default_report_path.is_file():
        METRIC_REPORT_PATH.write_text(
            default_report_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    p_new, p_champion = _metric_values(report)
    return {
        "metric_report": str(METRIC_REPORT_PATH),
        "holdout_quarter": holdout_quarter,
        "precision_at_10_new": p_new,
        "precision_at_10_champion": p_champion,
        "batch_path": str(path),
    }


def choose_deploy_branch(**context: object) -> str:
    if not METRIC_REPORT_PATH.is_file():
        raise FileNotFoundError(f"metric report not found: {METRIC_REPORT_PATH}")

    report = json.loads(METRIC_REPORT_PATH.read_text(encoding="utf-8"))
    p_new, p_champion = _metric_values(report)
    passed = p_new >= p_champion and p_new >= GATE_THRESHOLD
    branch = "register_model" if passed else "skip_deploy"
    LOGGER.info(
        "NBO metric gate: precision_at_10_new=%.6f precision_at_10_champion=%.6f "
        "threshold=%.6f decision=%s",
        p_new,
        p_champion,
        GATE_THRESHOLD,
        branch,
    )
    return branch


def register_and_promote(**context: object) -> dict[str, object]:
    train_result = _xcom_pull(context, "train") or {}
    version = train_result.get("mlflow_model_version")
    if not version:
        challenger = registry.get_challenger()
        version = challenger.get("version")
    if not version:
        raise RuntimeError("Cannot promote: challenger MLflow version is not available.")

    result = registry.promote(str(version))
    LOGGER.info("NBO traffic switch complete: %s", result)
    return {"status": "promoted", **result}


def keep_champion(**context: object) -> dict[str, str]:
    reason = "new model precision@10 below champion or threshold"
    skip = getattr(registry, "skip_deploy", None)
    if callable(skip):
        skip(reason)
    LOGGER.info("NBO deployment skipped: %s", reason)
    return {"status": "skipped", "reason": reason}


def _check_required_columns(data: pd.DataFrame, errors: list[str]) -> None:
    required = {"client_id"}
    missing = sorted(required - set(data.columns))
    if missing:
        errors.append(f"missing required columns: {missing}")

    if not ({"quarter", "reference_date", "ts"} & set(data.columns)):
        errors.append("missing quarter/reference_date/ts column")

    if not ({"product", "product_id"} & set(data.columns)) and not _product_one_hot_columns(data):
        errors.append("missing product/product_id or PROD_01..PROD_39 columns")

    if not ({"lifecycle_role", "event_type"} & set(data.columns)):
        errors.append("missing lifecycle_role/event_type column")


def _check_client_id(data: pd.DataFrame, errors: list[str]) -> None:
    if "client_id" not in data.columns:
        return
    null_count = int(data["client_id"].isna().sum())
    if null_count:
        errors.append(f"client_id has nulls: {null_count}")


def _check_quarter(data: pd.DataFrame, errors: list[str]) -> None:
    labels = _quarter_labels(data, errors)
    if labels is None:
        return
    bad = labels.isna() | ~labels.astype(str).str.match(QUARTER_RE)
    if bool(bad.any()):
        errors.append(f"quarter has invalid values: {int(bad.sum())}")
        return
    years = labels.astype(str).str.slice(0, 4).astype(int)
    out_of_range = ~years.between(2019, 2100)
    if bool(out_of_range.any()):
        errors.append(f"quarter year out of range: {int(out_of_range.sum())}")


def _check_product(data: pd.DataFrame, errors: list[str]) -> None:
    product_col = "product" if "product" in data.columns else "product_id" if "product_id" in data.columns else None
    if product_col is not None:
        values = data[product_col].astype("string").str.strip()
        bad = values.isna() | ~values.str.match(PRODUCT_RE)
        if bool(bad.any()):
            errors.append(f"{product_col} has invalid PROD_01..PROD_39 values: {int(bad.sum())}")
        return

    for col in _product_one_hot_columns(data):
        values = pd.to_numeric(data[col], errors="coerce")
        bad = values.isna() | ~values.isin([0, 1])
        if bool(bad.any()):
            errors.append(f"{col} one-hot values must be 0/1: {int(bad.sum())}")


def _check_role(data: pd.DataFrame, errors: list[str]) -> None:
    role_col = "lifecycle_role" if "lifecycle_role" in data.columns else "event_type" if "event_type" in data.columns else None
    if role_col is None:
        return
    values = data[role_col].astype("string").str.strip().str.lower()
    bad_null = values.isna() | values.eq("")
    if bool(bad_null.any()):
        errors.append(f"{role_col} has null/empty values: {int(bad_null.sum())}")
    bad_role = ~values.isin(ROLE_VALUES)
    if bool(bad_role.any()):
        errors.append(f"{role_col} has unknown public roles: {int(bad_role.sum())}")


def _check_segment(data: pd.DataFrame, errors: list[str]) -> None:
    if "segment" not in data.columns:
        return
    values = data["segment"].astype("string").str.strip()
    bad = values.notna() & values.ne("") & ~values.str.match(SEGMENT_RE)
    if bool(bad.any()):
        errors.append(f"segment has invalid SEG_0..SEG_6 values: {int(bad.sum())}")


def _check_score_ranges(data: pd.DataFrame, errors: list[str]) -> None:
    score_cols = [
        col
        for col in data.columns
        if str(col).lower() in SCORE_COLUMNS or str(col).lower().startswith("score_")
    ]
    for col in score_cols:
        values = pd.to_numeric(data[col], errors="coerce")
        present = values.notna()
        bad = present & ~values.between(0.0, 1.0)
        if bool(bad.any()):
            errors.append(f"{col} must be in [0, 1]: {int(bad.sum())}")


def _product_one_hot_columns(data: pd.DataFrame) -> list[str]:
    return [str(col) for col in data.columns if PRODUCT_RE.match(str(col))]


def _quarter_labels(data: pd.DataFrame, errors: list[str]) -> pd.Series | None:
    if "reference_date" in data.columns:
        return _date_to_quarter(data["reference_date"], errors, "reference_date")
    if "ts" in data.columns:
        return _date_to_quarter(data["ts"], errors, "ts")
    if "year" in data.columns and "quarter" in data.columns:
        year = pd.to_numeric(data["year"], errors="coerce")
        quarter = pd.to_numeric(data["quarter"], errors="coerce")
        bad = year.isna() | quarter.isna() | ~quarter.between(1, 4)
        labels = year.astype("Int64").astype("string") + "Q" + quarter.astype("Int64").astype("string")
        labels.loc[bad] = pd.NA
        return labels
    if "quarter" in data.columns:
        raw = data["quarter"]
        if pd.api.types.is_numeric_dtype(raw):
            values = pd.to_numeric(raw, errors="coerce")
            bad = values.isna() | ~values.between(1, 4)
            if bool(bad.any()):
                errors.append(f"quarter numeric values must be 1..4: {int(bad.sum())}")
            return None
        return raw.astype("string").str.strip().str.upper()
    return None


def _date_to_quarter(values: pd.Series, errors: list[str], col: str) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    bad = parsed.isna()
    if bool(bad.any()):
        errors.append(f"{col} has invalid dates: {int(bad.sum())}")
    labels = parsed.dt.to_period("Q-DEC").astype("string")
    labels.loc[bad] = pd.NA
    return labels


def _reference_quarter(batch_path: Path) -> str:
    if TRAIN_REFERENCE_QUARTER:
        return _normalize_quarter(TRAIN_REFERENCE_QUARTER)

    data = pd.read_parquet(batch_path)
    errors: list[str] = []
    labels = _quarter_labels(data, errors)
    if labels is None or errors:
        raise ValueError(
            "Cannot infer NBO_TRAIN_REFERENCE_QUARTER from batch; "
            "set NBO_TRAIN_REFERENCE_QUARTER explicitly."
        )
    clean = labels.dropna().astype(str)
    if clean.empty:
        raise ValueError("Cannot infer reference quarter from an empty quarter series.")
    max_quarter = max(clean, key=_quarter_index)
    return _previous_quarter(max_quarter)


def _feature_store_quarters(reference_quarter: str) -> list[str]:
    if FEATURE_STORE_QUARTERS:
        return [_normalize_quarter(item.strip()) for item in FEATURE_STORE_QUARTERS.split(",") if item.strip()]
    return [reference_quarter]


def _metric_values(report: dict[str, Any]) -> tuple[float, float]:
    if "precision_at_10_new" in report and "precision_at_10_champion" in report:
        return float(report["precision_at_10_new"]), float(report["precision_at_10_champion"])

    challenger = report.get("challenger")
    champion = report.get("champion")
    if isinstance(challenger, dict) and isinstance(champion, dict):
        return float(challenger["precision_at_10"]), float(champion["precision_at_10"])

    if "precision_at_10" in report and isinstance(report.get("uplift_vs_popularity"), dict):
        p_new = float(report["precision_at_10"])
        delta = float(report["uplift_vs_popularity"]["precision_at_10"])
        return p_new, p_new - delta

    raise KeyError(
        "metric_report.json must contain precision_at_10_new/precision_at_10_champion "
        "or challenger/champion precision_at_10."
    )


def _xcom_pull(context: dict[str, object], task_id: str) -> dict[str, Any] | None:
    task_instance = context.get("ti") or context.get("task_instance")
    if task_instance is None or not hasattr(task_instance, "xcom_pull"):
        return None
    value = task_instance.xcom_pull(task_ids=task_id)
    return value if isinstance(value, dict) else None


def _normalize_quarter(value: str) -> str:
    text = str(value).strip().upper()
    if not QUARTER_RE.match(text):
        raise ValueError(f"quarter must use YYYYQn format, got {value!r}")
    return text


def _quarter_index(value: str) -> int:
    label = _normalize_quarter(value)
    year, quarter = label.split("Q")
    return int(year) * 4 + int(quarter) - 1


def _quarter_from_index(value: int) -> str:
    year = value // 4
    quarter = value % 4 + 1
    return f"{year}Q{quarter}"


def _previous_quarter(value: str) -> str:
    return _quarter_from_index(_quarter_index(value) - 1)


def _next_quarter(value: str) -> str:
    return _quarter_from_index(_quarter_index(value) + 1)


default_args = {
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
}


with DAG(
    dag_id="nbo_retrain_pipeline",
    start_date=datetime(2026, 5, 1),
    schedule=DAG_SCHEDULE,
    catchup=False,
    default_args=default_args,
    tags=["ml005", "nbo", "continuous-training"],
) as dag:
    if USE_S3_SENSOR:
        wait_for_batch = S3KeySensor(
            task_id="wait_for_batch",
            bucket_key=S3_KEY_TEMPLATE,
            bucket_name=S3_BUCKET,
            aws_conn_id="aws_default",
            poke_interval=60,
            timeout=3600,
            mode="poke",
        )
    else:
        wait_for_batch = FileSensor(
            task_id="wait_for_batch",
            filepath=str(LOCAL_BATCH_PATH),
            fs_conn_id="fs_default",
            poke_interval=30,
            timeout=3600,
            mode="poke",
        )

    validate = PythonOperator(task_id="validate_data", python_callable=validate_batch_data)
    build = PythonOperator(task_id="build_features", python_callable=build_nbo_features)
    train = PythonOperator(task_id="train", python_callable=train_nbo_model)
    evaluate = PythonOperator(task_id="evaluate", python_callable=evaluate_nbo_model)
    compare = BranchPythonOperator(task_id="compare_with_champion", python_callable=choose_deploy_branch)
    register = PythonOperator(task_id="register_model", python_callable=register_and_promote)
    skip = PythonOperator(task_id="skip_deploy", python_callable=keep_champion)
    finish = EmptyOperator(
        task_id="finish",
        trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    )

    wait_for_batch >> validate >> build >> train >> evaluate >> compare
    compare >> register >> finish
    compare >> skip >> finish
