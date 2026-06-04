# Rubric mapping C1..C5

| criterion | requirement | artifact evidence | status |
|---|---|---|---|
| C1 | goal / one business metric / ML proxy / metric tree | `manifest.md` sections 7-8; `reports/metric_report.md`; `reports/metric_report.json` (`precision@10=0.003204`, `hit-rate@10=0.032043`, `uplift_precision=-0.000054`) | pass |
| C2 | maturity Level 2: versioning / CI-CD / feature store / serving API / monitoring / MLflow / Airflow / bad model blocked by alias-switch | `manifest.md` section 4; `src/registry.py`; `reports/registry_demo.md`; `dags/nbo_retrain_dag.py`; `reports/b07_dag_verification_log.md`; TODO screenshot targets `screenshots/mlflow_alias.png`, `screenshots/b07_gate_skip_deploy.png` | pending |
| C3 | IaC + working service + docker ps healthy + `/health` 200 | `infra/providers.tf`; `infra/main.tf`; `infra/variables.tf`; `infra/outputs.tf`; `.github/workflows/ci.yml`; `reports/terraform_plan.txt`; `screenshots/docker_ps_healthy.png`; `reports/api_smoke.md`; `screenshots/health_200_render.png` (render, not terminal capture) | pass |
| C4 | risks / SLI-SLO on 3 levels with critical thresholds | `docs/sli_slo.md`; `manifest.md` sections 7-8; `monitoring/prometheus.yml`; `monitoring/alerts/nbo_rules.yml`; `monitoring/grafana/dashboards/nbo_overview.json` | pass |
| C5 | MDD + ADR: H0/H1 / test / p-value / alpha / architecture decision | `adr/0001-latency-mdd-decision.md`; `reports/mdd_test_result.md`; `reports/mdd_latency_distribution.png`; `notebooks/mdd_latency.ipynb` | pass |

## Notes

- C2 is functionally present by code + CLI/API evidence, but browser screenshots for MLflow alias and Airflow gate are pending live capture.
- mandatory browser blockers are recorded in `screenshots/mlflow_ui_screenshot_blocker.md`, `reports/b07_dag_verification_log.md`, and `reports/b08_screenshot_blocker.txt`.
- no row is marked `pass` only from a missing screenshot.

**Вывод:** rubric is mostly pass; C2 stays pending until live browser screenshots are added.
