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
| `reports/mdd_latency_distribution.png` | распределения latency (existing vs improved) для MDD | C5 |

## Текстовые доказательства

| файл | что доказывает | критерий |
|---|---|---|
| `reports/api_smoke.md` | curl `/health` 200 + `/score` JSON (лог) | C3 / C1 |
| `reports/registry_demo.md` | mlflow alias champion/challenger, promote, rollback | C2 |
| `reports/b07_dag_verification_log.md` | импорт dag, дерево задач, решения gate (skip/register) | C2 |
| `reports/terraform_plan.txt` | terraform plan: манифесты стека (5 to add) | C3 |
| `docs/sli_slo.md` | SLI/SLO на 3 уровнях с критическими порогами | C4 |

**Вывод:** evidence по критериям C1, C2, C3, C5 снято; по C4 требование закрыто документом SLI/SLO. Визуальные кадры и текстовые логи покрывают весь контур: данные, обучение, registry, сервинг, оркестрация, инфраструктура.
