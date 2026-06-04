# Мониторинг NBO

Тут описано, как у сервиса устроен мониторинг: сбор метрик, дашборд и проверка дрифта данных.

## Что входит

- Prometheus собирает метрики: `nbo-api:8000/metrics`, `node_exporter:9100`, плюс сам себя.
- Grafana поднимается с готовым datasource `Prometheus` и дашбордом `NBO / NBO overview`.
- Drift job: `monitoring/evidently/drift_report.py`.
- Живые drift-метрики идут через node_exporter (textfile collector):
  - файл с метриками: `reports/prometheus/nbo_drift.prom`
  - метрики в Prometheus: `nbo_drift_share`, `nbo_dataset_drift`, `nbo_psi_max`

## Запуск

```bash
cd ml005
docker compose up -d nbo-api prometheus grafana node_exporter
```

Адреса:

- Prometheus: `http://localhost:${PROMETHEUS_PORT:-9090}`
- Grafana: `http://localhost:${GRAFANA_PORT:-3000}`
- Логин в Grafana (demo): `${GF_SECURITY_ADMIN_USER:-admin}` / `${GF_SECURITY_ADMIN_PASSWORD:-admin}`

Дашборд:

- папка: `NBO`
- имя: `NBO overview`

## Evidently / smoke-проверка дрифта

Команда на синтетике (для CI и старта):

```bash
cd ml005
python monitoring/evidently/drift_report.py \
  --reference data/sample_synth.parquet \
  --current data/sample_synth.parquet \
  --out reports/evidently_drift_smoke.html
```

Что должно получиться на одинаковой синтетике:

- html-отчет лежит в `reports/evidently_drift_smoke.html`
- в выводе есть `drift_share`
- textfile-метрики лежат в `reports/prometheus/nbo_drift.prom`

`reports/*.html` и `reports/prometheus/*.prom` в git не идут: отчеты на реальных данных держу локально.

## Контракт API-метрик

Источник: контракт метрик в `src/serve_api.py` и реализация `/metrics`.

| метрика | PromQL | панель |
|---|---|---|
| `nbo_request_latency_seconds_bucket` | `histogram_quantile(0.95, sum(rate(nbo_request_latency_seconds_bucket{job="nbo-api",endpoint="/score"}[5m])) by (le))` | `/score latency p95/p99` |
| `nbo_request_latency_seconds_bucket` | `histogram_quantile(0.99, sum(rate(nbo_request_latency_seconds_bucket{job="nbo-api",endpoint="/score"}[5m])) by (le))` | `/score latency p95/p99` |
| `nbo_requests_total` | `sum(rate(nbo_requests_total{job="nbo-api",endpoint="/score"}[5m]))` | `/score request rate` |
| `nbo_errors_total` / `nbo_requests_total` | `sum(rate(nbo_errors_total{job="nbo-api",endpoint="/score"}[5m])) / clamp_min(sum(rate(nbo_requests_total{job="nbo-api",endpoint="/score"}[5m])), 0.001)` | `/score error-rate` |
| `nbo_score_distribution_bucket` | для разовых проверок распределения score | нет в первом дашборде |
| `nbo_not_scorable_total` | для проверок population-filter | нет в первом дашборде |
| `nbo_drift_share` | `max(nbo_drift_share)` | `Drift share` |
| `nbo_psi_max` | `max(nbo_psi_max)` | `Max PSI` |

## Алерты

Prometheus подгружает `monitoring/alerts/nbo_rules.yml`.

Правила:

- `NBOHighErrorRate`: критично, когда error-rate `/score` > 3% в течение 5 минут (порог предварительный, откалибрую на baseline).
- `NBOHighP95Latency`: критично, когда p95 latency `/score` > 800 мс в течение 5 минут (порог предварительный, откалибрую на baseline).

Recording-правила:

- `nbo:score_latency_p95_seconds`
- `nbo:score_latency_p99_seconds`
- `nbo:score_error_rate`

## Контракт DAG (b07)

Импорт:

```python
from monitoring.evidently.drift_report import build_drift_report
```

Контракт функции:

```python
build_drift_report(reference_df, current_df, score_col, target_cols, out_html) -> dict
```

Возвращаемые ключи:

- `dataset_drift`
- `drift_share`
- `n_drifted_features`
- `psi_max`
- `generated_at`

Сейчас Airflow в этом `docker-compose.yml` не отдает метрики в Prometheus, поэтому панель `DAG success-rate` в Grafana остается текстовой. Если добавить statsd-exporter или Airflow Prometheus exporter, ее можно заменить на PromQL-панель.
