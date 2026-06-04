# MLflow registry demo

## scope

- compose service: `mlflow`
- container: `ml005_mlflow`
- tracking URI used by host client: `http://localhost:15000`
- registered model: `nbo_topn`
- aliases: `champion`, `challenger`
- artifact storage: MLflow artifact proxy -> container volume `/mlflow/artifacts`
- demo models: sklearn `DummyClassifier` on synthetic public columns only
- metrics source: `reports/metric_report.json`
- feature hash source: `artifacts/feature_list.json`

## docker evidence

Command:

```bash
MLFLOW_PORT=15000 docker compose up -d mlflow && MLFLOW_PORT=15000 docker compose ps
```

Output:

```text
NAME           IMAGE              COMMAND                  SERVICE   STATUS         PORTS
ml005_mlflow   python:3.12-slim   "/bin/sh -lc ' pip i..." mlflow    Up 2 minutes   0.0.0.0:15000->5000/tcp, [::]:15000->5000/tcp
```

Command:

```bash
curl -so /dev/null -w '%{http_code}' http://localhost:${MLFLOW_PORT:-15000}
```

Output:

```text
200
```

## run/register evidence

Command:

```bash
MLFLOW_TRACKING_URI=http://localhost:${MLFLOW_PORT:-15000} MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python <demo-log-script>
```

Output:

```json
{
  "run1": "f5c601a185a44432a1093cc0e3f93269",
  "version1": "1",
  "run2": "79d468b2c0c54c1485e5547e07242f90",
  "version2": "2"
}
```

## alias switch evidence

Command:

```bash
export MLFLOW_TRACKING_URI=http://localhost:${MLFLOW_PORT:-15000}
export MLFLOW_MODEL_NAME=nbo_topn
.venv/bin/python -m src.registry --show
.venv/bin/python -m src.registry --promote 2
.venv/bin/python -m src.registry --show
.venv/bin/python -m src.registry --rollback
.venv/bin/python -m src.registry --show
```

Output:

```text
SHOW_INITIAL
model: nbo_topn
champion: version=1 run_id=f5c601a185a44432a1093cc0e3f93269
challenger: version=2 run_id=79d468b2c0c54c1485e5547e07242f90
PROMOTE_2
{
  "model": "nbo_topn",
  "champion": "2",
  "previous": "1"
}
SHOW_AFTER_PROMOTE
model: nbo_topn
champion: version=2 run_id=79d468b2c0c54c1485e5547e07242f90
challenger: version=2 run_id=79d468b2c0c54c1485e5547e07242f90
ROLLBACK
{
  "model": "nbo_topn",
  "champion": "1",
  "rolled_back_from": "2"
}
SHOW_AFTER_ROLLBACK
model: nbo_topn
champion: version=1 run_id=f5c601a185a44432a1093cc0e3f93269
challenger: version=2 run_id=79d468b2c0c54c1485e5547e07242f90
```

## model-info evidence

Command:

```bash
MLFLOW_TRACKING_URI=http://localhost:${MLFLOW_PORT:-15000} MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python - <<'PY'
import json
from src.registry import get_model_info
print(json.dumps(get_model_info(), ensure_ascii=True, indent=2, sort_keys=True))
PY
```

Output:

```json
{
  "champion_version": "1",
  "challenger_version": "2",
  "data_cutoff": "2022Q1",
  "feature_list_hash": "b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a",
  "model": "nbo_topn"
}
```

## screenshots

- blocked: no project Playwright setup, no `playwright` binary, no browser binary in PATH.
- per local `$playwright-ui-test` rule, new browser/test tooling was not installed without direct approval.
- UI availability still verified by HTTP 200 and MLflow run/model links printed by the client:
  - run champion: `http://localhost:15000/#/experiments/1/runs/f5c601a185a44432a1093cc0e3f93269`
  - run challenger: `http://localhost:15000/#/experiments/1/runs/79d468b2c0c54c1485e5547e07242f90`

## notes

- [assumption] `python:3.12-slim` fallback is used because `ghcr.io/mlflow/mlflow:v2.22.5` was not found.
- [assumption] demo models are alias-mechanism evidence only. b03 can call `registry.log_run` with the full contract when it starts passing the model object and feature hash.
- artifact backend: local Docker named volume `mlflow_data`.

## b05-fix evidence

Updated at: 2026-05-31 23:38:32 MSK

### F1 healthcheck

Command:

```bash
MLFLOW_PORT=15000 docker compose up -d --force-recreate mlflow
docker compose ps mlflow
docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-health{{end}}' ml005_mlflow
```

Output:

```text
NAME           IMAGE              COMMAND                  SERVICE   CREATED          STATUS                    PORTS
ml005_mlflow   python:3.12-slim   "/bin/sh -lc ' pip i..." mlflow    58 seconds ago   Up 46 seconds (healthy)   0.0.0.0:15000->5000/tcp, [::]:15000->5000/tcp
health=healthy
```

### F2 real train -> registry lineage

Command:

```bash
MLFLOW_TRACKING_URI=http://localhost:15000 MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python -m src.train --quarter 2021Q4 --backend logreg --min-support 50 --seed 42
```

Output:

```json
{
  "model_path": "/home/x39963/web/niki/mo-dz/ml005/models/model.pkl",
  "meta_path": "/home/x39963/web/niki/mo-dz/ml005/models/meta.json",
  "metrics": {
    "n_train_rows": 32814,
    "n_holdout_rows": 5555,
    "n_products_catalog": 25,
    "macro_auc_challenger": 0.8029591572613823,
    "seed": 42,
    "backend": "logreg",
    "min_support": 50,
    "n_auc_products": 25
  },
  "run_id": "nbo_train_20260531_203754",
  "mlflow_run_id": "90f1cb77351a4b2dbd6b00a6e5ad2cf0",
  "mlflow_model_version": "4"
}
```

Command:

```bash
MLFLOW_TRACKING_URI=http://localhost:15000 MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python -m src.registry --show
```

Output:

```text
model: nbo_topn
champion: version=1 run_id=f5c601a185a44432a1093cc0e3f93269
challenger: version=4 run_id=90f1cb77351a4b2dbd6b00a6e5ad2cf0
```

Command:

```bash
MLFLOW_TRACKING_URI=http://localhost:15000 MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python - <<'PY'
import json
from pathlib import Path
from src.registry import get_challenger
feature_hash = json.loads(Path('artifacts/feature_list.json').read_text(encoding='utf-8'))['hash']
info = get_challenger()
print(json.dumps({
    'version': info['version'],
    'run_id': info['run_id'],
    'feature_hash_matches': info['feature_list_hash'] == feature_hash,
    'feature_list_hash': info['feature_list_hash'],
    'metrics': info['metrics'],
    'model_path': info.get('model_path'),
}, ensure_ascii=True, indent=2, sort_keys=True))
PY
```

Output:

```json
{
  "feature_hash_matches": true,
  "feature_list_hash": "b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a",
  "metrics": {
    "macro_auc_challenger": 0.8029591572613823,
    "min_support": 50.0,
    "n_auc_products": 25.0,
    "n_holdout_rows": 5555.0,
    "n_products_catalog": 25.0,
    "n_train_rows": 32814.0,
    "seed": 42.0
  },
  "model_path": "/home/x39963/web/niki/mo-dz/ml005/models/model.pkl",
  "run_id": "90f1cb77351a4b2dbd6b00a6e5ad2cf0",
  "version": "4"
}
```

### F2 promote / rollback

Command:

```bash
MLFLOW_TRACKING_URI=http://localhost:15000 MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python -m src.registry --promote 4
MLFLOW_TRACKING_URI=http://localhost:15000 MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python -m src.registry --rollback
```

Output:

```text
PROMOTE_4
{
  "model": "nbo_topn",
  "champion": "4",
  "previous": "1"
}
GET_CHAMPION_AFTER_REAL_PROMOTE
{
  "feature_list_hash": "b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a",
  "metrics": {
    "macro_auc_challenger": 0.8029591572613823,
    "min_support": 50.0,
    "n_auc_products": 25.0,
    "n_holdout_rows": 5555.0,
    "n_products_catalog": 25.0,
    "n_train_rows": 32814.0,
    "seed": 42.0
  },
  "model_path": "/home/x39963/web/niki/mo-dz/ml005/models/model.pkl",
  "run_id": "90f1cb77351a4b2dbd6b00a6e5ad2cf0",
  "version": "4"
}
ROLLBACK
{
  "model": "nbo_topn",
  "champion": "1",
  "rolled_back_from": "4"
}
```

### b06/b07 contract update

- registry version now points to a real b03 training run (`mlflow_run_id=90f1cb77351a4b2dbd6b00a6e5ad2cf0`, version `4`).
- model bytes stay in gitignored `MODEL_DIR/model.pkl`; MLflow stores a small pointer artifact and metadata tags only.
- b06 loads model bytes from local `MODEL_DIR/model.pkl`/`model_path` and reads version/hash/metrics via `get_champion()`.
- b07 calls `promote(version)` only after metric gate; `rollback()` remains the emergency revert.
