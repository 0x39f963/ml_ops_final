# Демонстрация реестра моделей MLflow

## что показываем

- сервис в compose: `mlflow`
- контейнер: `ml005_mlflow`
- адрес для клиента с хоста: `http://localhost:15000`
- зарегистрированная модель: `nbo_topn`
- алиасы: `champion`, `challenger`
- хранилище артефактов: artifact-прокси MLflow -> том контейнера `/mlflow/artifacts`
- демо-модели: sklearn `DummyClassifier` только на публичных синтетических колонках
- источник метрик: `reports/metric_report.json`
- источник хэша признаков: `artifacts/feature_list.json`

## контейнер mlflow поднят

Команда:

```bash
MLFLOW_PORT=15000 docker compose up -d mlflow && MLFLOW_PORT=15000 docker compose ps
```

Вывод:

```text
NAME           IMAGE              COMMAND                  SERVICE   STATUS         PORTS
ml005_mlflow   python:3.12-slim   "/bin/sh -lc ' pip i..." mlflow    Up 2 minutes   0.0.0.0:15000->5000/tcp, [::]:15000->5000/tcp
```

Команда:

```bash
curl -so /dev/null -w '%{http_code}' http://localhost:${MLFLOW_PORT:-15000}
```

Вывод:

```text
200
```

## создание и регистрация версий модели

Команда:

```bash
MLFLOW_TRACKING_URI=http://localhost:${MLFLOW_PORT:-15000} MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python <demo-log-script>
```

Вывод (две версии модели):

```json
{
  "run1": "f5c601a185a44432a1093cc0e3f93269",
  "version1": "1",
  "run2": "79d468b2c0c54c1485e5547e07242f90",
  "version2": "2"
}
```

## переключение alias: promote и rollback

Это и есть управление трафиком: `promote` делает версию рабочей (champion), `rollback` возвращает предыдущую.

Команда:

```bash
export MLFLOW_TRACKING_URI=http://localhost:${MLFLOW_PORT:-15000}
export MLFLOW_MODEL_NAME=nbo_topn
.venv/bin/python -m src.registry --show
.venv/bin/python -m src.registry --promote 2
.venv/bin/python -m src.registry --show
.venv/bin/python -m src.registry --rollback
.venv/bin/python -m src.registry --show
```

Вывод (исходное состояние -> promote версии 2 -> rollback на версию 1):

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

## информация о модели (model-info)

Команда:

```bash
MLFLOW_TRACKING_URI=http://localhost:${MLFLOW_PORT:-15000} MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python - <<'PY'
import json
from src.registry import get_model_info
print(json.dumps(get_model_info(), ensure_ascii=True, indent=2, sort_keys=True))
PY
```

Вывод:

```json
{
  "champion_version": "1",
  "challenger_version": "2",
  "data_cutoff": "2022Q1",
  "feature_list_hash": "b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a",
  "model": "nbo_topn"
}
```

Ссылки на прогоны в MLflow UI (доступность подтверждена кодом 200):

- champion: `http://localhost:15000/#/experiments/1/runs/f5c601a185a44432a1093cc0e3f93269`
- challenger: `http://localhost:15000/#/experiments/1/runs/79d468b2c0c54c1485e5547e07242f90`

## примечания

- образ `python:3.12-slim` используется как запасной, так как `ghcr.io/mlflow/mlflow:v2.22.5` не нашелся.
- демо-модели здесь нужны только чтобы показать механику alias; реальная модель регистрируется в разделе ниже.
- бэкенд артефактов: локальный docker-том `mlflow_data`.

## реальная обученная модель в registry (train -> alias)

### healthcheck mlflow

Команда:

```bash
MLFLOW_PORT=15000 docker compose up -d --force-recreate mlflow
docker compose ps mlflow
docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-health{{end}}' ml005_mlflow
```

Вывод (контейнер в состоянии healthy):

```text
NAME           IMAGE              COMMAND                  SERVICE   CREATED          STATUS                    PORTS
ml005_mlflow   python:3.12-slim   "/bin/sh -lc ' pip i..." mlflow    58 seconds ago   Up 46 seconds (healthy)   0.0.0.0:15000->5000/tcp, [::]:15000->5000/tcp
health=healthy
```

### обучение реальной модели и регистрация

Команда:

```bash
MLFLOW_TRACKING_URI=http://localhost:15000 MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python -m src.train --quarter 2021Q4 --backend logreg --min-support 50 --seed 42
```

Вывод (модель обучена, метрики посчитаны, версия зарегистрирована):

```json
{
  "model_path": "models/model.pkl",
  "meta_path": "models/meta.json",
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

Команда:

```bash
MLFLOW_TRACKING_URI=http://localhost:15000 MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python -m src.registry --show
```

Вывод (challenger теперь указывает на реальный обученный прогон):

```text
model: nbo_topn
champion: version=1 run_id=f5c601a185a44432a1093cc0e3f93269
challenger: version=4 run_id=90f1cb77351a4b2dbd6b00a6e5ad2cf0
```

Проверка, что хэш признаков challenger совпадает с контрактом `feature_list.json`:

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

Вывод (`feature_hash_matches: true` - паритет train/serve соблюден):

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
  "model_path": "models/model.pkl",
  "run_id": "90f1cb77351a4b2dbd6b00a6e5ad2cf0",
  "version": "4"
}
```

### promote и rollback реальной версии

Команда:

```bash
MLFLOW_TRACKING_URI=http://localhost:15000 MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python -m src.registry --promote 4
MLFLOW_TRACKING_URI=http://localhost:15000 MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python -m src.registry --rollback
```

Вывод (версию 4 вывели в champion, затем откатили):

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
  "model_path": "models/model.pkl",
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

### что из этого следует для сервинга и dag

- версия в registry указывает на реальный обучающий прогон (`mlflow_run_id=90f1cb77351a4b2dbd6b00a6e5ad2cf0`, версия `4`).
- байты модели лежат в gitignored `MODEL_DIR/model.pkl`; в MLflow хранится только маленький artifact-указатель и метаданные (теги).
- сервис (b06) грузит байты модели из локального `MODEL_DIR/model.pkl`, а версию/хэш/метрики читает через `get_champion()`.
- dag (b07) вызывает `promote(version)` только после прохождения metric-gate; `rollback()` - аварийный откат.
