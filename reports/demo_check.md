# Проверка demo UI - лог

## что показываем

- демо-интерфейс на Streamlit + health-sidecar на FastAPI
- сервис в compose: `nbo-demo`
- зависит от API `nbo-api` по адресу `http://nbo-api:8000` внутри compose
- только публичные идентификаторы: `client_id`, `PROD_01..PROD_39`, `SEG_0..SEG_6`

## команды и доказательства

Команда (синтаксис и валидность compose):

```bash
python3 -c "import ast; ast.parse(open('demo/app.py').read()); print('app parse ok')"
python3 -c "import ast; ast.parse(open('demo/health.py').read()); print('health parse ok')"
docker compose config --quiet
```

Вывод:

```text
app parse ok
health parse ok
compose config exit code 0
```

Команда (health-sidecar отвечает 200):

```bash
uvicorn health:app --host 0.0.0.0 --port 18512
curl -s -o /tmp/nbo_demo_health_18512_body.txt -w '%{http_code}' http://localhost:18512/health
```

Вывод:

```text
200
{"status":"ok","service":"nbo-demo"}
```

Примечание: локальный порт `8502` был занят другим процессом, поэтому локальный smoke sidecar использовал `18512`. В compose host-порт `18502`.

Команда (поднять demo + api, проверить статусы):

```bash
docker compose up -d --build nbo-api nbo-demo
docker compose ps
```

Вывод (оба сервиса healthy):

```text
NAME          IMAGE              COMMAND                  SERVICE    STATUS                    PORTS
nbo-demo      ml005-nbo-demo     "/bin/sh /app/demo/e..." nbo-demo   Up 21 seconds (healthy)   0.0.0.0:18501->8501/tcp, 0.0.0.0:18502->8502/tcp
nbo_mlflow    python:3.12-slim   "/bin/sh -lc ' pip i..." mlflow     Up 4 minutes (healthy)    0.0.0.0:5000->5000/tcp
nbo_nbo-api   ml005-nbo-api      "uvicorn src.serve_a..." nbo-api    Up 30 seconds (healthy)   0.0.0.0:8000->8000/tcp
```

Команда (demo health и открытие UI):

```bash
curl -s -o /tmp/nbo_demo_health_compose_body.txt -w '%{http_code}' http://localhost:18502/health
cat /tmp/nbo_demo_health_compose_body.txt
curl -s -o /tmp/nbo_demo_ui_head.html -w '%{http_code}' http://localhost:18501
```

Вывод:

```text
200
{"status":"ok","service":"nbo-demo"}
200
```

Команда (health самого API):

```bash
curl -s http://localhost:8000/health
```

Вывод:

```json
{"status":"ok","model_version":"1","champion_alias":"champion","data_cutoff":"2026Q1"}
```

Команда (скоринг по клиенту):

```bash
curl -s -X POST http://localhost:8000/score -H 'Content-Type: application/json' -d '{"client_id":"C0004e3cbdfb8","reference_date":"2026Q1","mode":"single"}'
```

Кратко из вывода (scorable, топ-10, верхний продукт PROD_33):

```text
status=scorable
client_id=C0004e3cbdfb8
segment_id=SEG_3
model_version=1
top_n=10
top_product=PROD_33
caveats=value is propensity proxy only, not revenue; cutoff = latest completed quarter (2026Q1)
```

Команда (клиент, которого нельзя скорить):

```bash
curl -s -X POST http://localhost:8000/score -H 'Content-Type: application/json' -d '{"client_id":"C00005e0ce441","reference_date":"2026Q1","mode":"single"}'
```

Кратко из вывода (честный not_scorable, score=null, без выдуманного списка):

```text
status=not_scorable
client_id=C00005e0ce441
score=null
recommended_action=no scoring: client not in scorable population
reason=low evidence or no public entity mapping
```

Команда (demo вызывает API изнутри контейнера):

```bash
docker exec -i nbo-demo python - <<'PY'
import app
resp = app.score_client('C0004e3cbdfb8', '2026Q1')
print(resp.get('status'), len(resp.get('score') or []), resp.get('score', [{}])[0].get('product'))
resp2 = app.score_client('C00005e0ce441', '2026Q1')
print(resp2.get('status'), resp2.get('score'))
PY
```

Вывод:

```text
scorable 10 PROD_33
not_scorable None
```

Команда (поведение при недоступном API - честная ошибка, без падения):

```bash
docker exec -i nbo-demo python - <<'PY'
import os
os.environ['API_BASE_URL'] = 'http://127.0.0.1:9'
import app
print(app.score_client('C0004e3cbdfb8', '2026Q1').get('_error', 'no error')[:160])
PY
```

Вывод:

```text
serving API unavailable - check nbo-api / API_BASE_URL: HTTPConnectionPool(host='127.0.0.1', port=9): Max retries exceeded with url: /score
```

Команда (анти-лик):

```bash
make leak-check
git status --porcelain | grep -E '\.pkl$|\.joblib$|\.parquet$|mlruns|\.env$'
```

Вывод (leak-check зеленый, запрещенных файлов в git нет):

```text
checking gitignore gates
checking tracked and staged file list
leak-check passed
forbidden-status-grep output: empty
```

## примечания

- сначала сервис (b06) был `degraded`, так как у активного MLflow не был назначен champion. Для этого локального прогона в работающем MLflow зарегистрировали демо-версию champion с тегами `feature_list_hash`, `model_path`, `data_cutoff=2026Q1`, после чего `nbo-api` перезапустили.
- этот шаг поменял только локальное runtime-состояние в gitignored томах MLflow/модели. В git не добавлено ни байтов модели, ни parquet, ни `.env`, ни `mlruns`.
- `API_BASE_URL` по умолчанию `http://localhost:8000` для локального запуска, потому что `docker-compose.yml` публикует API как `${NBO_API_PORT:-8000}:8000`. Внутри compose трафик demo идет на `http://nbo-api:8000`.
