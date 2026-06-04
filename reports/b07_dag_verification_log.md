# b07 DAG verification log

## local parse and smoke

Command:

```bash
python3 -m py_compile ml005/dags/nbo_retrain_dag.py && echo PARSE_OK
python3 -m compileall -q ml005/src ml005/dags ml005/tests && echo COMPILEALL_OK
python3 -m pytest tests/test_dag_import.py -q
```

Output:

```text
PARSE_OK
COMPILEALL_OK
3 passed in 0.64s
```

## callable checks

Command:

```bash
NBO_BATCH_PATH=data/sample_synth.parquet python3 - <<'PY'
import importlib.util
from pathlib import Path
path = Path('dags/nbo_retrain_dag.py')
spec = importlib.util.spec_from_file_location('nbo_retrain_dag_check', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
report = module.validate_batch_data()
print({'status': report['status'], 'n_rows': report['n_rows']})
print('gate_branch', module.choose_deploy_branch())
PY
```

Output:

```text
{'status': 'pass', 'n_rows': 40000}
gate_branch skip_deploy
```

Command:

```bash
python3 <temp bad parquet validation check>
```

Output:

```text
NBO batch validation failed
```

## compose snippet

Command:

```bash
docker compose -f docker-compose.yml -f dags/airflow_compose_snippet.yml config --services
docker compose -f docker-compose.yml -f dags/airflow_compose_snippet.yml config >/tmp/ml005_b07_compose_config.yml && echo COMPOSE_CONFIG_OK
```

Output:

```text
mlflow
nbo-api
airflow
COMPOSE_CONFIG_OK
```

## airflow import and graph

Command:

```bash
docker compose -f docker-compose.yml -f dags/airflow_compose_snippet.yml up -d --force-recreate airflow
docker compose -f docker-compose.yml -f dags/airflow_compose_snippet.yml exec -T airflow airflow dags list | grep nbo_retrain_pipeline
docker compose -f docker-compose.yml -f dags/airflow_compose_snippet.yml exec -T airflow airflow dags list-import-errors
docker compose -f docker-compose.yml -f dags/airflow_compose_snippet.yml exec -T airflow airflow tasks list nbo_retrain_pipeline --tree
curl -s -o /tmp/ml005_airflow_health.html -w '%{http_code}\n' http://localhost:18080/health
```

Output:

```text
nbo_retrain_pipeline | /opt/airflow/dags/nbo_retrain_dag.py | airflow | True
No data found
200
<Task(FileSensor): wait_for_batch>
    <Task(PythonOperator): validate_data>
        <Task(PythonOperator): build_features>
            <Task(PythonOperator): train>
                <Task(PythonOperator): evaluate>
                    <Task(BranchPythonOperator): compare_with_champion>
                        <Task(PythonOperator): register_model>
                            <Task(EmptyOperator): finish>
                        <Task(PythonOperator): skip_deploy>
                            <Task(EmptyOperator): finish>
```

## airflow task checks

Command:

```bash
docker compose -f docker-compose.yml -f dags/airflow_compose_snippet.yml exec -T airflow airflow tasks test nbo_retrain_pipeline validate_data 2026-05-30
docker compose -f docker-compose.yml -f dags/airflow_compose_snippet.yml exec -T airflow airflow tasks test nbo_retrain_pipeline compare_with_champion 2026-05-30
docker compose -f docker-compose.yml -f dags/airflow_compose_snippet.yml exec -T airflow bash -lc 'printf "%s\n" "{\"precision_at_10_new\": 0.20, \"precision_at_10_champion\": 0.10}" > /tmp/good_metric_report.json && NBO_METRIC_REPORT=/tmp/good_metric_report.json NBO_GATE_PRECISION_AT_10_THRESHOLD=0.10 airflow tasks test nbo_retrain_pipeline compare_with_champion 2026-05-31'
```

Output:

```text
NBO batch validation passed: {'status': 'pass', 'n_rows': 40000, 'errors': [], 'path': '/opt/airflow/data/sample_synth.parquet'}
NBO metric gate: precision_at_10_new=0.003204 precision_at_10_champion=0.003258 threshold=0.100000 decision=skip_deploy
Branch into skip_deploy
NBO metric gate: precision_at_10_new=0.200000 precision_at_10_champion=0.100000 threshold=0.100000 decision=register_model
Branch into register_model
```

## anti-leak

Command:

```bash
make leak-check
git check-ignore -v data/real.parquet data/feature_store/q=2022Q1/part.parquet models/model.pkl models/model.joblib mlruns/0/meta.yaml .env src/__pycache__/x.pyc
```

Output:

```text
leak-check passed
.gitignore:7:data/**/*.parquet data/real.parquet
.gitignore:8:data/feature_store/ data/feature_store/q=2022Q1/part.parquet
.gitignore:17:*.pkl models/model.pkl
.gitignore:18:*.joblib models/model.joblib
.gitignore:19:mlruns/ mlruns/0/meta.yaml
.gitignore:25:.env .env
.gitignore:29:*/__pycache__/ src/__pycache__/x.pyc
```

## screenshots

- `screenshots/b07_dag_graph.png`: not collected; no local browser or Playwright binary in PATH.
- Airflow CLI graph render was also blocked because Graphviz `dot` is not installed in the Airflow image.
- `screenshots/b07_dag_run_success.png`: not collected; full DAG run with train/register was not executed in this pass.
- `screenshots/b07_gate_skip_deploy.png`: not collected; CLI gate evidence is captured above.
