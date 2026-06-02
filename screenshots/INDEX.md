Generated at: 2026-06-01 17:37:04 MSK

# Evidence screenshots index

| evidence | file / fallback | what it proves | criterion |
|---|---|---|---|
| docker ps Up(healthy) | `screenshots/docker_ps_healthy.png` | compose services show Up / healthy on local stack | C3 |
| docker ps text source | `screenshots/docker_ps_healthy.md` | command output behind the docker screenshot | C3 |
| `/health` 200 text evidence | `reports/api_smoke.md` | live `curl http://localhost:18000/health` -> HTTP 200 + JSON body, captured as text log | C3 |
| `/health` 200 render | `screenshots/health_200_render.png` | text render of live `/health` response, not a terminal capture | C3 |
| terraform plan | `reports/terraform_plan.txt` | Terraform local provider plan creates stack manifests | C3 |
| MLflow alias | `reports/registry_demo.md` | `champion` / `challenger` aliases, promote and rollback evidence | C2 |
| MLflow UI screenshot blocker | `screenshots/mlflow_ui_screenshot_blocker.md` | browser capture unavailable; UI HTTP 200 and registry links logged | C2 |
| Airflow DAG/gate | `reports/b07_dag_verification_log.md` | DAG import, task tree, gate skip/register decisions from CLI | C2 |
| Airflow UI screenshot target | TODO `screenshots/b07_dag_run_success.png`, TODO `screenshots/b07_gate_skip_deploy.png`, TODO `screenshots/b07_dag_graph.png` | pending live browser capture | C2 |
| Grafana dashboard | `reports/b08_grafana_dashboard.json`, `reports/b08_grafana_search.json` | dashboard is provisioned through API evidence | C4 |
| Grafana screenshot target | TODO `screenshots/b08_grafana_overview.png` | pending live browser capture | C4 |
| Prometheus targets | `reports/b08_prometheus_targets.json` | targets API evidence collected instead of browser screenshot | C4 |
| Evidently report | `reports/evidently_drift_smoke.html` | synthetic drift report generated | C4 |
| Evidently screenshot target | TODO `screenshots/b08_evidently_report.png` | pending live browser capture | C4 |
| demo UI render | `screenshots/demo_score_render.png` | top-10 render from verified live `/score` response | C3 |
| demo UI screenshot target | TODO `screenshots/demo_top10.png`, TODO `screenshots/b11_demo_ui.png` | pending real Streamlit browser capture | C3 |
| MDD plot | `reports/mdd_latency_distribution.png` | existing vs improved latency distribution | C5 |

## Pending live capture

- `screenshots/mlflow_alias.png` - MLflow registered model UI with aliases
- `screenshots/api_health.png` - real browser/terminal capture of `/health` 200
- `screenshots/b07_dag_graph.png` - Airflow DAG graph
- `screenshots/b07_dag_run_success.png` - successful Airflow DAG run
- `screenshots/b07_gate_skip_deploy.png` - gate skip deploy branch
- `screenshots/b08_prometheus_targets.png` - Prometheus targets UI
- `screenshots/b08_grafana_overview.png` - Grafana overview dashboard
- `screenshots/b08_evidently_report.png` - Evidently HTML report in browser
- `screenshots/demo_top10.png` or `screenshots/b11_demo_ui.png` - real Streamlit UI screenshot

**Вывод:** mandatory backend evidence exists for docker / health / terraform / registry / API. Browser UI screenshots remain pending because browser tooling was absent in this environment.
