# Rubric mapping C1..C5

| criterion | requirement | artifact evidence | status |
|---|---|---|---|
| C1 | goal / one business metric / ML proxy / metric tree | `manifest.md` sections 7-8; `reports/metric_report.md`; `reports/metric_report.json` (`precision@10=0.003204`, `hit-rate@10=0.032043`); `screenshots/api_swagger.png`; `screenshots/demo_top10.png` | pass |
| C2 | maturity Level 2: versioning / CI-CD / feature store / serving API / monitoring / MLflow / Airflow / bad model blocked by alias-switch | `manifest.md` section 4; `src/registry.py`; `reports/registry_demo.md`; `dags/nbo_retrain_dag.py`; `reports/b07_dag_verification_log.md`; `screenshots/airflow_dags.png`; `screenshots/airflow_dag_run.png` | pass |
| C3 | IaC + working service + docker ps healthy + `/health` 200 | `infra/*.tf`; `.github/workflows/ci.yml`; `reports/terraform_plan.txt`; `screenshots/docker_ps_healthy.png`; `screenshots/docker_stats.png`; `screenshots/api_health.png`; `reports/api_smoke.md` | pass |
| C4 | risks / SLI-SLO on 3 levels with critical thresholds | `docs/sli_slo.md`; `monitoring/prometheus.yml`; `monitoring/alerts/nbo_rules.yml`; `monitoring/grafana/dashboards/nbo_overview.json` | pass |
| C5 | MDD + ADR: H0/H1 / test / p-value / alpha / architecture decision | `adr/0001-latency-mdd-decision.md`; `reports/mdd_test_result.md`; `reports/mdd_latency_distribution.png`; `notebooks/mdd_latency.ipynb` | pass |

Каждый критерий закрыт кодом, документом и визуальным доказательством. Скриншоты - в `screenshots/`, сводный каталог - `screenshots/INDEX.md`.
