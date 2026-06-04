# Сверка по критериям C1..C5

Свел в таблицу, что требовалось по заданию и чем я это закрыл: код, документ и визуальное доказательство по каждому из пяти критериев.

| критерий | что требуется | чем закрыл | статус |
|---|---|---|---|
| C1 | цель / одна бизнес-метрика / ML-прокси / дерево метрик | `manifest.md` разделы 7-8; `reports/metric_report.md`; `reports/metric_report.json` (`precision@10=0.003204`, `hit-rate@10=0.032043`); `screenshots/api_swagger.png`; `screenshots/demo_top10.png` | выполнено |
| C2 | зрелость Level 2: версионирование / CI-CD / feature store / serving API / мониторинг / MLflow / Airflow / вывод плохой модели через переключение alias | `manifest.md` раздел 4; `src/registry.py`; `reports/registry_demo.md`; `dags/nbo_retrain_dag.py`; `reports/b07_dag_verification_log.md`; `screenshots/airflow_dags.png`; `screenshots/airflow_dag_run.png`; `screenshots/mlflow_experiments.png` | выполнено |
| C3 | IaC + работающий сервис + docker ps healthy + `/health` 200 | `infra/*.tf`; `.github/workflows/ci.yml`; `reports/terraform_plan.txt`; `screenshots/docker_ps_healthy.png`; `screenshots/docker_stats.png`; `screenshots/api_health.png`; `screenshots/ci_green.png`; `reports/api_smoke.md` | выполнено |
| C4 | риски / SLI-SLO на 3 уровнях с критическими порогами | `docs/sli_slo.md`; `monitoring/prometheus.yml`; `monitoring/alerts/nbo_rules.yml`; `monitoring/grafana/dashboards/nbo_overview.json`; `reports/load_test.md`; `reports/drift_monitoring.md`; `screenshots/prometheus_targets.png`; `screenshots/grafana_drift.png`; `screenshots/evidently_drift_summary.png` | выполнено |
| C5 | MDD + ADR: H0/H1 / тест / p-value / alpha / архитектурное решение | `adr/0001-latency-mdd-decision.md`; `reports/mdd_test_result.md`; `reports/mdd_latency_distribution.png`; `notebooks/mdd_latency.ipynb` | выполнено |

Каждый критерий закрыт кодом, документом и визуальным доказательством. Скриншоты - в `screenshots/`, сводный каталог - `screenshots/INDEX.md`.
