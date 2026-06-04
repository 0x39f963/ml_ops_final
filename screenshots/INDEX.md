# Evidence screenshots index

Каталог визуальных доказательств. Все кадры с localhost, только публичные имена (`client_id`-хэш, `PROD_xx`, `SEG_x`).

## Снято (в репозитории)

| файл | что доказывает | критерий |
|---|---|---|
| `screenshots/docker_ps_healthy.png` | docker-сервисы в состоянии Up(healthy) | C3 |
| `screenshots/api_health.png` | `/health` -> 200, модель загружена по alias champion | C3 |
| `screenshots/api_swagger.png` | контракт scoring-API: /health /score /batch-score /model-info /metrics | C1 |
| `screenshots/demo_top10.png` | demo по клиенту -> топ-10 продуктов (режим inn: инн хэшируется в браузере) | C1 |
| `screenshots/airflow_dags.png` | airflow dag nbo_retrain_pipeline - конвейер переобучения | C2 |
| `screenshots/airflow_dag_run.png` | прогон dag со всеми задачами + ветка register_model / skip_deploy | C2 |
| `screenshots/mlflow_experiments.png` | mlflow: эксперимент nbo_topn, прогоны обучения, зарегистрированная модель v1 | C2 |
| `screenshots/ci_green.png` | github actions зеленый: checks (compile + smoke) + terraform (fmt/validate/plan) | C3 |
| `screenshots/prometheus_targets.png` | prometheus targets все UP: nbo-api, node_exporter, prometheus | C4 |
| `screenshots/grafana_drift.png` | grafana дрифт: drift share 30%, max psi 27.6 (2024 vs 2025) | C4 |
| `screenshots/evidently_drift_summary.png` | evidently: 4 из 9 столбцов сдвинулись между 2024 и 2025 | C4 |
| `screenshots/evidently_drift_project_summary.png` | проектная сводка дрифта: drift_share 0.3, psi_max 27.63 | C4 |
| `screenshots/prometheus_drift.png` | drift-метрики в prometheus: nbo_drift_share / dataset_drift / psi_max | C4 |
| `screenshots/grafana_overview.png` | grafana nbo_overview под нагрузкой: rps 1.62k, timeouts 0, latency p95/p99, drift/psi | C4 |
| `reports/mdd_latency_distribution.png` | распределения latency (existing vs improved) для MDD | C5 |

## Текстовые доказательства

| файл | что доказывает | критерий |
|---|---|---|
| `reports/api_smoke.md` | curl `/health` 200 + `/score` JSON (лог) | C3 / C1 |
| `reports/registry_demo.md` | mlflow alias champion/challenger, promote, rollback | C2 |
| `reports/b07_dag_verification_log.md` | импорт dag, дерево задач, решения gate (skip/register) | C2 |
| `reports/terraform_plan.txt` | terraform plan: манифесты стека (5 to add) | C3 |
| `reports/load_test.md` | нагрузочный тест /score: 50k запросов, 0 таймаутов, p95 289 мс (slo p95 < 500 мс) | C4 / C1 |
| `reports/drift_monitoring.md` | дрифт входных данных: 2024 vs 2025, drift share 0.30, max psi 27.63, объяснение | C4 |
| `docs/sli_slo.md` | SLI/SLO на 3 уровнях с критическими порогами | C4 |

**Вывод:** evidence по всем критериям C1-C5 снято. По C4, кроме документа SLI/SLO, есть и живые кадры: prometheus targets UP и нагрузочный тест с проверкой технического порога latency. Визуальные кадры и текстовые логи покрывают весь контур: данные, обучение, registry, сервинг, оркестрация, инфраструктура, мониторинг.
