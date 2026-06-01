Generated at: 2026-06-01 17:06:52 MSK

## demo check

## scope

- branch: b11 demo UI
- framework: Streamlit UI plus FastAPI health sidecar
- compose service: `nbo-demo`
- API dependency: `nbo-api` at `http://nbo-api:8000` inside compose
- public identifiers only: `client_id`, `PROD_01..PROD_39`, `SEG_0..SEG_6`

## commands and evidence

Command:

```bash
python3 -c "import ast; ast.parse(open('demo/app.py').read()); print('app parse ok')"
python3 -c "import ast; ast.parse(open('demo/health.py').read()); print('health parse ok')"
docker compose config --quiet
```

Output:

```text
app parse ok
health parse ok
compose config exit code 0
```

Command:

```bash
uvicorn health:app --host 0.0.0.0 --port 18512
curl -s -o /tmp/nbo_demo_health_18512_body.txt -w '%{http_code}' http://localhost:18512/health
```

Output:

```text
200
{"status":"ok","service":"nbo-demo"}
```

Note: local port `8502` was already occupied by another process, so sidecar local smoke used `18512`. Compose uses host port `18502`.

Command:

```bash
docker compose up -d --build nbo-api nbo-demo
docker compose ps
```

Output:

```text
NAME          IMAGE              COMMAND                  SERVICE    STATUS                    PORTS
nbo-demo      ml005-nbo-demo     "/bin/sh /app/demo/e..." nbo-demo   Up 21 seconds (healthy)   0.0.0.0:18501->8501/tcp, 0.0.0.0:18502->8502/tcp
nbo_mlflow    python:3.12-slim   "/bin/sh -lc ' pip i..." mlflow     Up 4 minutes (healthy)    0.0.0.0:5000->5000/tcp
nbo_nbo-api   ml005-nbo-api      "uvicorn src.serve_a..." nbo-api    Up 30 seconds (healthy)   0.0.0.0:8000->8000/tcp
```

Command:

```bash
curl -s -o /tmp/nbo_demo_health_compose_body.txt -w '%{http_code}' http://localhost:18502/health
cat /tmp/nbo_demo_health_compose_body.txt
curl -s -o /tmp/nbo_demo_ui_head.html -w '%{http_code}' http://localhost:18501
```

Output:

```text
200
{"status":"ok","service":"nbo-demo"}
200
```

Command:

```bash
curl -s http://localhost:8000/health
```

Output:

```json
{"status":"ok","model_version":"1","champion_alias":"champion","data_cutoff":"2026Q1"}
```

Command:

```bash
curl -s -X POST http://localhost:8000/score -H 'Content-Type: application/json' -d '{"client_id":"C0004e3cbdfb8","reference_date":"2026Q1","mode":"single"}'
```

Output summary:

```text
status=scorable
client_id=C0004e3cbdfb8
segment_id=SEG_3
model_version=1
top_n=10
top_product=PROD_33
caveats=value is propensity proxy only, not revenue; cutoff = latest completed quarter (2026Q1)
```

Command:

```bash
curl -s -X POST http://localhost:8000/score -H 'Content-Type: application/json' -d '{"client_id":"C00005e0ce441","reference_date":"2026Q1","mode":"single"}'
```

Output summary:

```text
status=not_scorable
client_id=C00005e0ce441
score=null
recommended_action=no scoring: client not in scorable population
reason=low evidence or no public entity mapping
```

Command:

```bash
docker exec -i nbo-demo python - <<'PY'
import app
resp = app.score_client('C0004e3cbdfb8', '2026Q1')
print(resp.get('status'), len(resp.get('score') or []), resp.get('score', [{}])[0].get('product'))
resp2 = app.score_client('C00005e0ce441', '2026Q1')
print(resp2.get('status'), resp2.get('score'))
PY
```

Output:

```text
scorable 10 PROD_33
not_scorable None
```

Command:

```bash
docker exec -i nbo-demo python - <<'PY'
import os
os.environ['API_BASE_URL'] = 'http://127.0.0.1:9'
import app
print(app.score_client('C0004e3cbdfb8', '2026Q1').get('_error', 'no error')[:160])
PY
```

Output:

```text
serving API unavailable - check nbo-api / API_BASE_URL: HTTPConnectionPool(host='127.0.0.1', port=9): Max retries exceeded with url: /score
```

Command:

```bash
make leak-check
git status --porcelain | grep -E '\.pkl$|\.joblib$|\.parquet$|mlruns|\.env$'
```

Output:

```text
checking gitignore gates
checking tracked and staged file list
leak-check passed
forbidden-status-grep output: empty
```

## screenshot evidence

- data-render artifact: `screenshots/demo_score_render.png`
- source: generated from the verified live `/score` response for `client_id=C0004e3cbdfb8`
- contents: top-10 public `PROD_*` products, probability bars, `SEG_3`, `model_version=1`, caveats
- this file is a data-render from live `/score`, not a browser screenshot of the Streamlit UI
- canonical UI screenshot path: `screenshots/demo_top10.png`
- canonical UI screenshot status: manual TODO for owner
- browser capture status: blocked by environment
- blocker evidence: no `playwright` binary, no Python Playwright/Selenium package, no Chrome/Chromium/Firefox binary, no project `ui-checks` or Playwright config found
- constraint followed: no browser/test package was installed without direct approval

## manual UI screenshot TODO

- owner opens `http://localhost:${DEMO_PORT:-18501}` in a browser
- owner enters a scorable synthetic `client_id` such as `C0004e3cbdfb8`
- owner clicks `Score`
- owner verifies only public names are visible: `client_id`, `PROD_*`, `SEG_*`
- owner saves the real Streamlit UI screenshot as `screenshots/demo_top10.png`
- optional: owner saves a not_scorable UI state screenshot after scoring `C00005e0ce441`
- health evidence already collected by agent: `curl http://localhost:18502/health` returned HTTP 200

## notes

- b06 was initially `degraded` because the active MLflow server had no champion alias. For this local evidence run, a demo champion version was registered in the running MLflow container with tags `feature_list_hash`, `model_path=/app/models/model.pkl`, and `data_cutoff=2026Q1`; then `nbo-api` was restarted.
- This bootstrap changed only local runtime state in ignored MLflow/model volumes. It did not add model bytes, parquet files, `.env`, or `mlruns` to git.
- `API_BASE_URL` defaults to `http://localhost:8000` for local use because the current `docker-compose.yml` exposes b06 as `${NBO_API_PORT:-8000}:8000`. Compose overrides demo traffic to `http://nbo-api:8000`.
