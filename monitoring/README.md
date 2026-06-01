Generated at: 2026-06-01 13:00:25 MSK

# NBO monitoring

## Что входит

- Prometheus scrape: `nbo-api:8000/metrics`, `node-exporter:9100`, self-scrape.
- Grafana provisioning: datasource `Prometheus`, dashboard `NBO / NBO overview`.
- Drift job: `monitoring/evidently/drift_report.py`.
- Drift live metrics: variant A, node_exporter textfile collector.
  - output file: `reports/prometheus/nbo_drift.prom`
  - Prometheus metrics: `nbo_drift_share`, `nbo_dataset_drift`, `nbo_psi_max`

## Run

```bash
cd ml005
docker compose up -d nbo-api prometheus grafana node-exporter
```

URLs:

- Prometheus: `http://localhost:${PROM_PORT:-9090}`
- Grafana: `http://localhost:${GRAFANA_PORT:-3000}`
- Grafana demo login: `${GF_SECURITY_ADMIN_USER:-admin}` / `${GF_SECURITY_ADMIN_PASSWORD:-admin}`

Dashboard:

- folder: `NBO`
- name: `NBO overview`

## Evidently / drift smoke

Synthetic-only command for CI/boot:

```bash
cd ml005
python monitoring/evidently/drift_report.py \
  --reference data/sample_synth.parquet \
  --current data/sample_synth.parquet \
  --out reports/evidently_drift_smoke.html
```

Expected smoke result on identical synthetic data:

- HTML report exists at `reports/evidently_drift_smoke.html`
- printed summary has `drift_share`
- textfile metrics exist at `reports/prometheus/nbo_drift.prom`

`reports/*.html` and `reports/prometheus/*.prom` are gitignored, because real-data reports are local-only.

## API metric contract

Evidence source: `src/serve_api.py` metric contract and `/metrics` implementation.

| metric name | PromQL | panel |
|---|---|---|
| `nbo_request_latency_seconds_bucket` | `histogram_quantile(0.95, sum(rate(nbo_request_latency_seconds_bucket{job="nbo-api",endpoint="/score"}[5m])) by (le))` | `/score latency p95/p99` |
| `nbo_request_latency_seconds_bucket` | `histogram_quantile(0.99, sum(rate(nbo_request_latency_seconds_bucket{job="nbo-api",endpoint="/score"}[5m])) by (le))` | `/score latency p95/p99` |
| `nbo_requests_total` | `sum(rate(nbo_requests_total{job="nbo-api",endpoint="/score"}[5m]))` | `/score request rate` |
| `nbo_errors_total` / `nbo_requests_total` | `sum(rate(nbo_errors_total{job="nbo-api",endpoint="/score"}[5m])) / clamp_min(sum(rate(nbo_requests_total{job="nbo-api",endpoint="/score"}[5m])), 0.001)` | `/score error-rate` |
| `nbo_score_distribution_bucket` | available for ad-hoc score distribution checks | not in first dashboard |
| `nbo_not_scorable_total` | available for population-filter checks | not in first dashboard |
| `nbo_drift_share` | `max(nbo_drift_share)` | `Drift share` |
| `nbo_psi_max` | `max(nbo_psi_max)` | `Max PSI` |

## Alerts

Prometheus loads `monitoring/alerts/nbo_rules.yml`.

Rules:

- `NBOHighErrorRate`: critical when `/score` error-rate > 3 percent for 5m [assumption].
- `NBOHighP95Latency`: critical when `/score` p95 latency > 800 ms for 5m [assumption].

Recording rules:

- `nbo:score_latency_p95_seconds`
- `nbo:score_latency_p99_seconds`
- `nbo:score_error_rate`

## DAG contract for b07

Import path:

```python
from monitoring.evidently.drift_report import build_drift_report
```

Function contract:

```python
build_drift_report(reference_df, current_df, score_col, target_cols, out_html) -> dict
```

Returned keys include:

- `dataset_drift`
- `drift_share`
- `n_drifted_features`
- `psi_max`
- `generated_at`

Current DAG state: [assumption] Airflow Prometheus exporter is not configured in the current `docker-compose.yml`. The Grafana DAG success panel is a text note until b07/b09 adds statsd-exporter or an Airflow Prometheus exporter.
