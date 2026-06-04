# Smoke-проверка API - доказательства

## что показываем

- сервис: `nbo-api`
- контейнер: `nbo-api`
- внутренний порт: `8000`
- host-порт: `${API_PORT:-18000}`
- адрес MLflow в compose: `http://mlflow:5000`
- имя модели: `nbo_topn`
- alias, который читает API: `champion`
- контракт признаков: `artifacts/feature_list.json`
- feature_list_hash: `b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a`

## контракт метрик (для мониторинга)

| метрика | тип | лейблы | что значит |
|---|---|---|---|
| `nbo_requests_total` | Counter | `endpoint`, `status_code` | число запросов к API (без self-scrape `/metrics`) |
| `nbo_errors_total` | Counter | `endpoint` | ответы 5xx и необработанные ошибки |
| `nbo_request_latency_seconds` | Histogram | `endpoint` | время ответа; корзины покрывают пороги SLO 0.5s и 0.8s |
| `nbo_score_distribution` | Histogram | `model_role` | распределение вероятностей в выдаче топ-N |
| `nbo_not_scorable_total` | Counter | нет | сколько запросов ушло в not_scorable |

## синтаксис

Команда:

```bash
python3 -c "import ast; ast.parse(open('src/serve_api.py').read()); print('parse ok')"
```

Вывод:

```text
parse ok
```

## тесты (pytest)

Команда:

```bash
python3 -m pytest -q tests/test_api.py
```

Вывод:

```text
........                                                                 [100%]
8 passed, 3 warnings in 0.98s
```

Примечания:

- предупреждения - от fallback b02: `Feature store partition 2026Q1 is missing; building on the fly`.
- тесты подменяют старт на dummy-модель и синтетическую популяцию; ни MLflow-сервер, ни Docker не нужны.

## локальный запуск (uvicorn) - smoke

Команда:

```bash
MLFLOW_TRACKING_URI=http://localhost:15000 MLFLOW_MODEL_NAME=nbo_topn API_PORT=18000 .venv/bin/python -m uvicorn src.serve_api:app --host 0.0.0.0 --port 18000
```

Лог старта:

```text
MLflow artifact does not expose an NBO product scoring interface.
Application startup complete.
Uvicorn running on http://0.0.0.0:18000
```

API прочитал метаданные alias `champion`, затем взял локальный `MODEL_DIR/model.pkl`, потому что текущий champion-артефакт в MLflow - это демо-sklearn без интерфейса скоринга продуктов. Локальный fallback разрешен только если метаданные локальной модели совпадают с хэшем `feature_list`; роль `champion` выбирается из локального бандла.

### health

Команда:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:18000/health
curl -s http://localhost:18000/health | python3 -m json.tool
```

Вывод:

```text
200
```

```json
{
    "status": "ok",
    "model_version": "1",
    "champion_alias": "champion",
    "data_cutoff": "2022Q1"
}
```

### score: клиента можно скорить

Команда:

```bash
curl -s -X POST http://localhost:18000/score -H "Content-Type: application/json" -d '{"client_id":"C0004e3cbdfb8","reference_date":"2026Q1"}' | python3 -m json.tool
```

Вывод (топ-10 продуктов с вероятностью + caveats):

```json
{
    "client_id": "C0004e3cbdfb8",
    "model_version": "1",
    "segment_id": null,
    "status": "scorable",
    "score": [
        {"product": "PROD_21", "p": 0.004571, "decision": "hold", "confidence": "low"},
        {"product": "PROD_24", "p": 0.004206, "decision": "hold", "confidence": "low"},
        {"product": "PROD_12", "p": 0.003962, "decision": "hold", "confidence": "low"},
        {"product": "PROD_05", "p": 0.003931, "decision": "hold", "confidence": "low"},
        {"product": "PROD_13", "p": 0.003931, "decision": "hold", "confidence": "low"},
        {"product": "PROD_09", "p": 0.003901, "decision": "hold", "confidence": "low"},
        {"product": "PROD_02", "p": 0.003657, "decision": "hold", "confidence": "low"},
        {"product": "PROD_07", "p": 0.003596, "decision": "hold", "confidence": "low"},
        {"product": "PROD_22", "p": 0.003596, "decision": "hold", "confidence": "low"},
        {"product": "PROD_04", "p": 0.003535, "decision": "hold", "confidence": "low"}
    ],
    "recommended_action": "offer top product PROD_21",
    "caveats": [
        "value is propensity proxy only, not revenue",
        "cutoff = latest completed quarter (2022Q1)"
    ]
}
```

### score: клиента нельзя скорить (честный not_scorable)

Команда:

```bash
curl -s -X POST http://localhost:18000/score -H "Content-Type: application/json" -d '{"client_id":"C_NOT_IN_POPULATION","reference_date":"2026Q1"}' | python3 -m json.tool
```

Вывод (status not_scorable, score=null, без выдуманного списка):

```json
{
    "client_id": "C_NOT_IN_POPULATION",
    "model_version": "1",
    "segment_id": null,
    "status": "not_scorable",
    "score": null,
    "recommended_action": "no scoring: client not in scorable population",
    "caveats": [
        "value is propensity proxy only, not revenue",
        "cutoff = latest completed quarter (2022Q1)",
        "not_scorable reason = no client mapping"
    ]
}
```

### model-info

Команда:

```bash
curl -s http://localhost:18000/model-info | python3 -m json.tool
```

Фрагмент вывода:

```json
{
    "model_name": "nbo_topn",
    "version": "1",
    "alias": "champion",
    "feature_list_hash": "b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a",
    "data_cutoff": "2022Q1",
    "status": "ok"
}
```

### metrics

Команда:

```bash
curl -s http://localhost:18000/metrics | grep -E "nbo_requests_total|nbo_request_latency_seconds_bucket|nbo_score_distribution_bucket|nbo_errors_total|nbo_not_scorable_total" | sed -n '1,80p'
```

Фрагмент вывода (метрики в формате Prometheus):

```text
# HELP nbo_requests_total HTTP requests handled by the NBO API.
# TYPE nbo_requests_total counter
nbo_requests_total{endpoint="/health",status_code="200"} 6.0
nbo_requests_total{endpoint="/score",status_code="200"} 1.0
# HELP nbo_errors_total HTTP 5xx responses and uncaught handler errors.
# TYPE nbo_errors_total counter
nbo_request_latency_seconds_bucket{endpoint="/score",le="0.5"} 1.0
nbo_score_distribution_bucket{le="0.1",model_role="champion"} 10.0
nbo_score_distribution_bucket{le="0.9",model_role="champion"} 10.0
nbo_not_scorable_total 0.0
```

## docker compose

Команда:

```bash
docker compose config -q
docker compose up -d --build nbo-api
docker compose ps
docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-health{{end}}' nbo-api
```

Вывод (контейнер nbo-api в состоянии healthy):

```text
NAME           IMAGE              COMMAND                  SERVICE   CREATED         STATUS                   PORTS
ml005_mlflow   python:3.12-slim   "/bin/sh -lc ' pip i..." mlflow    8 hours ago     Up 8 hours (healthy)     0.0.0.0:15000->5000/tcp, [::]:15000->5000/tcp
nbo-api        ml005-nbo-api      "uvicorn src.serve_a..." nbo-api   8 seconds ago   Up 6 seconds (healthy)   0.0.0.0:18000->8000/tcp, [::]:18000->8000/tcp
healthy
```

## доработка b06: выбор роли champion из локального бандла

### проверка: из бандла грузится именно champion

Команда:

```bash
MLFLOW_TRACKING_URI=http://localhost:15000 MLFLOW_MODEL_NAME=nbo_topn .venv/bin/python - <<'PY'
from src import serve_api
from src.data_wrappers import load_scoring_registry
from src.features import get_features
import joblib

serve_api.load_model()
print('model_kind', serve_api.STATE['model_kind'])
print('version', serve_api.STATE['version'])
print('status', 'ok' if serve_api.STATE['model'] is not None else 'degraded')
client = str(load_scoring_registry().loc[lambda d: d['scoring_status'].eq('SCORABLE'), 'client_id'].iloc[0])
X = get_features([{'client_id': client, 'quarter': serve_api.STATE['data_cutoff']}], serve_api.STATE['data_cutoff'])
bundle = joblib.load('models/model.pkl')
champ_top = bundle['champion'].rank(X.iloc[0], top_n=3)
chall_top = bundle['challenger'].predict_proba_topn(X, top_n=3)[0]
print('client', client)
print('champion_top3', champ_top)
print('challenger_top3', chall_top)
print('different_top3', champ_top != chall_top)
PY
```

Вывод (`model_kind = local_joblib_champion`, выдачи champion и challenger разные):

```text
model_kind local_joblib_champion
version 1
status ok
client C0004e3cbdfb8
champion_top3 [('PROD_21', 0.004571), ('PROD_24', 0.004206), ('PROD_12', 0.003962)]
challenger_top3 [('PROD_18', 0.863807), ('PROD_22', 0.862831), ('PROD_17', 0.854993)]
different_top3 True
```

### мелкие правки

- убрана неиспользуемая локальная переменная `cutoff_end` в `_score_clients`.
- `FAMILY_ALIASES` оставлен локальной копией, так как b02 держит исходный маппинг приватным (`features._SYNTH_FAMILY_ALIASES`); в коде добавлен комментарий-ссылка на источник.
- grep на мертвый `cutoff_end`, старую ветку "challenger-first", masking-маркеры и сырые имена продуктов - пусто.

### docker после правок

Команда:

```bash
docker compose up -d --build nbo-api
docker compose ps
curl -s http://localhost:18000/health | python3 -m json.tool
```

Вывод:

```text
NAME           IMAGE              COMMAND                  SERVICE   CREATED          STATUS                   PORTS
ml005_mlflow   python:3.12-slim   "/bin/sh -lc ' pip i..." mlflow    10 hours ago     Up 10 hours (healthy)    0.0.0.0:15000->5000/tcp, [::]:15000->5000/tcp
nbo-api        ml005-nbo-api      "uvicorn src.serve_a..." nbo-api   12 seconds ago   Up 8 seconds (healthy)   0.0.0.0:18000->8000/tcp, [::]:18000->8000/tcp
```

```json
{
    "status": "ok",
    "model_version": "1",
    "champion_alias": "champion",
    "data_cutoff": "2022Q1"
}
```

## анти-лик

Команда:

```bash
git -C . status --porcelain | grep -E "\.pkl$|\.joblib$|\.parquet$|mlruns|\.env$" || true
```

Вывод (пусто - запрещенных файлов в git нет):

```text
```

Ни байтов модели, ни parquet, ни mlruns, ни `.env` в git-статусе не появилось.
