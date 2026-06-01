Generated at: 2026-06-01 13:00:25 MSK

# NBO SLI/SLO

Числовые пороги - [assumption] до baseline-прогона (master TZ section 6 + b04/b12). После baseline обновить пороги, но не удалять timestamp-header.

## Technical

| SLI | source | normal | warning | critical | incident-action |
|---|---|---|---|---|---|
| `/health` availability | Prometheus blackbox or curl smoke [assumption], current API endpoint `GET /health` | >= 99% demo window [assumption] | 97-99% [assumption] | < 97% [assumption] | restart API / inspect MLflow alias / rollback container |
| p95 `/score` latency | Prometheus: `histogram_quantile(0.95, sum(rate(nbo_request_latency_seconds_bucket{job="nbo-api",endpoint="/score"}[5m])) by (le))` | < 500 ms cached [assumption] | 500-800 ms [assumption] | > 800 ms [assumption] | check cache/model load / scale API / reduce request path IO |
| API error-rate | Prometheus: `sum(rate(nbo_errors_total{job="nbo-api",endpoint="/score"}[5m])) / clamp_min(sum(rate(nbo_requests_total{job="nbo-api",endpoint="/score"}[5m])), 0.001)` | < 1% [assumption] | 1-3% [assumption] | > 3% [assumption] | rollback champion / inspect feature parity / stop bad deploy |
| DAG success-rate | Airflow DAG state now; Prometheus exporter [unknown] | >= 95% [assumption] | 90-95% [assumption] | < 90% [assumption] | inspect failed task / rerun after data fix / block promote |
| containers | `docker compose ps`, future Prometheus `up` | Up or healthy [assumption] | restart > 1 [assumption] | down [assumption] | redeploy service / inspect logs / restore volume |

## Model-Data

| SLI | source | normal | warning | critical | incident-action |
|---|---|---|---|---|---|
| validation critical checks | DAG `validate_data` result / report JSON | 100% pass [assumption] | not_applicable | any fail [assumption] | block train / fix batch / rerun validation |
| feature missingness for scorable clients | feature QA report or DAG validation summary [assumption] | < 2% [assumption] | 2-5% [assumption] | > 5% [assumption] | block or flag scoring / inspect source data |
| precision@10 vs champion | `reports/metric_report.json`, MLflow run metrics | >= champion + threshold [assumption] | equal to champion [assumption] | < champion [assumption] | skip deploy / keep champion alias |
| drift share | Evidently summary + Prometheus `nbo_drift_share` textfile metric | < 0.20 [assumption] | 0.20-0.40 [assumption] | > 0.40 [assumption] | rerun validation / inspect feature drift / retrain if stable |
| training-serving parity | API load checks + feature_list hash | pass [assumption] | not_applicable | fail [assumption] | block promote / rebuild feature_list / rollback alias |

## Business

| SLI | source | normal | warning | critical | incident-action |
|---|---|---|---|---|---|
| hit-rate@10 | delayed Q+1 campaign outcomes / manual baseline [assumption] | >= baseline campaign [assumption] | -10% vs baseline [assumption] | -25% vs baseline [assumption] | review model / review offer policy / rollback recommendation set |
| scorable coverage | scoring registry status counts / API not_scorable rate | >= baseline [assumption] | -5% vs baseline [assumption] | -15% vs baseline [assumption] | investigate data ingestion / entity mapping / low-evidence rule |
| low-confidence offer share | score output distribution / `nbo_score_distribution_bucket` [assumption] | <= threshold [assumption] | threshold..1.5x [assumption] | > 1.5x [assumption] | tighten gate / cap offers / review feature drift |
| sales workload rec/day | campaign planner or manual baseline [assumption] | <= team capacity [assumption] | near capacity [assumption] | > capacity [assumption] | cap top-N / throttle batch / prioritize high-confidence clients |

**Вывод:** b08 gives live technical + drift observability now. Business SLI needs delayed feedback after Q+1, so values stay [assumption] until baseline evidence exists.
