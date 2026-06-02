Generated at: 2026-06-01 17:37:04 MSK

# ML-005 manifest

## 1. Предыстория

- домен: B2B software license vendor, публично обезличенный
- lifecycle клиента: покупка -> активация -> продление -> апгрейд
- задача: next-best-offer для sales
- вход: `client_id` + `reference_date`
- выход: top-10 продуктов `PROD_01..PROD_39` с вероятностью Q+1

Evidence:

- API contract: `src/serve_api.py`
- synthetic public schema: `src/gen_synthetic.py`, `data/sample_synth.parquet`
- feature contract: `artifacts/feature_list.json`

**Вывод:** берем не сегмент как финальный ответ, а продуктовый top-N.

---

## 2. Ценностное предложение

- меньше ручного перебора у sales
- выше шанс попасть в продукт, который клиент купит / продлит в Q+1
- explainable top-10: продукт / `p` / decision / confidence / caveats
- единый scoring-контур: features -> model -> registry -> API -> monitoring
- честный `not_scorable`: score `null`, без выдуманных рекомендаций

Evidence:

- `/score` response shape: `reports/api_smoke.md`
- demo render: `screenshots/demo_score_render.png`
- README endpoint contract: `README.md`

---

## 3. Цели

- отдать top-10 по `client_id` с вероятностью `p`
- держать metric gate против деградации
- переобучать модель через Airflow DAG
- мониторить latency / errors / drift / business proxy
- разделить роли: CI проверяет код, DAG обучает модель

Evidence:

- DAG: `dags/nbo_retrain_dag.py`
- gate evidence: `reports/b07_dag_verification_log.md`
- CI: `.github/workflows/ci.yml`
- monitoring: `monitoring/prometheus.yml`, `docs/sli_slo.md`

---

## 4. Решение + заявленный Level 2

**Заявлен Level 2.**

Что есть в контуре:

- FastAPI scoring: `src/serve_api.py`
- Airflow retraining DAG: `dags/nbo_retrain_dag.py`
- MLflow registry: `src/registry.py`
- feature store / parity list: `src/features.py`, `artifacts/feature_list.json`
- champion/challenger: `src/train.py`, `reports/registry_demo.md`
- offline eval: `src/evaluate.py`, `reports/metric_report.json`
- monitoring: `monitoring/prometheus.yml`, `monitoring/grafana/dashboards/nbo_overview.json`, `monitoring/evidently/drift_report.py`
- IaC/CI: `infra/*.tf`, `.github/workflows/ci.yml`, `docker-compose.yml`

Вне продукта:

- streaming / Kafka / Spark
- Kubernetes
- partner-модель
- реальная выручка / LTV
- cloud VM deploy (P2 перед защитой)

**Вывод:** Level 2 заявлен не только текстом: есть registry / DAG gate / serving / monitoring / CI / IaC.

---

## 5. Осуществимость

- PIT feature layer уже вынесен в отдельный слой проекта
- scoring registry и quarterly timeline используются как концепт, в `ml005/` публично идут только wrappers + synthetic stub
- локальный docker stack поднимает API / registry / DAG / monitoring / demo
- ресурсная модель: 1 разработчик, локальный Docker, далее 1 VM
- временной план: квартальный batch scoring + delayed Q+1 feedback

Evidence:

- feature build: `src/features.py`
- synthetic boot: `Makefile`, target `data`
- stack: `docker-compose.yml`
- docker evidence: `screenshots/docker_ps_healthy.png`

---

## 6. Данные

- public source contract: `client_id`, `ts`, `year`, `quarter`, `product`, `product_family`, `segment`, `lifecycle_role`
- product ids: `PROD_01..PROD_39`
- segment ids: `SEG_0..SEG_6`
- target: `y=1`, если событие по продукту случилось в Q+1
- temporal split: train Q <= Q_t, holdout Q_t+1
- PIT guard: фичи считаются только до cutoff конца Q
- no-INN / low-evidence path: `not_scorable`

Evidence:

- generator: `src/gen_synthetic.py`
- labels: `src/labels.py`
- PIT tests: `tests/test_features.py`
- API not_scorable evidence: `reports/api_smoke.md`

---

## 7. Метрики

Главная business metric:

- `hit-rate@10` - доля клиентов, где хотя бы один продукт из top-10 реализовался в Q+1

ML proxy:

- `precision@10`
- `recall@10`
- `MAP@10`
- `NDCG@10`
- per-product AUC
- uplift vs popularity champion

Metric tree:

```text
business:   hit-rate@10 / offer acceptance
model:      precision@10 / MAP@10 / recall@10 / per-product AUC
technical:  p95/p99 latency / error-rate / DAG success / drift
```

Evidence:

- `reports/metric_report.json`
- `reports/metric_report.md`
- `docs/sli_slo.md`

---

## 8. Оценка качества (offline/online)

Offline holdout (`reports/metric_report.json`, generated at `2026-05-31 22:44:22 MSK`):

| metric | challenger | champion | uplift abs |
|---|---:|---:|---:|
| precision@10 | 0.003204 | 0.003258 | -0.000054 |
| recall@10 | 0.474667 | 0.482667 | -0.008000 |
| MAP@10 | 0.145997 | 0.162301 | -0.016304 |
| NDCG@10 | 0.221149 | 0.235570 | -0.014421 |
| hit-rate@10 | 0.032043 | 0.032583 | -0.000540 |
| per-product AUC macro | 0.802959 | 0.541206 | 0.261753 |

Context:

- holdout quarter: `2022Q1`
- evaluated clients: `5555`
- catalog after min-support: `25` products
- scorable share: `1.0`

Online plan:

- delayed Q+1 hit-rate@10 after campaign outcomes
- score drift / feature drift via Evidently
- API latency / errors via Prometheus

**Вывод:** на synthetic stub challenger не проходит precision@10 vs champion, поэтому gate должен оставить champion.

---

## 9. Подбор модели

- champion: popularity / segment prior / co-occurrence baseline
- challenger v1: LogReg OneVsRest, balanced classes
- challenger target: LightGBM per product (когда нужен сильнее backend)
- gate owner: Airflow DAG, не `train.py`
- gate policy: new precision@10 >= champion precision@10 AND >= threshold

Evidence:

- training code: `src/train.py`
- labels: `src/labels.py`
- eval report: `reports/metric_report.md`
- DAG gate: `dags/nbo_retrain_dag.py`

---

## 10. Инференс (batch/realtime)

- batch: квартальный scoring / materialized feature store / registry pointer
- realtime-ish: on-demand single-client request через API
- request path: чтение кэша / feature store + model inference
- без live remote sync в request path
- batch-score endpoint есть для списка клиентов
- `/metrics` отдает Prometheus telemetry

Evidence:

- API: `src/serve_api.py`
- `/health` text evidence: `reports/api_smoke.md`
- `/health` render evidence (not terminal capture): `screenshots/health_200_render.png`
- API smoke: `reports/api_smoke.md`
- MDD ADR: `adr/0001-latency-mdd-decision.md`

---

## 11. Обратная связь + MDD

- feedback loop: фактические события Q+1 -> новый batch -> DAG retrain -> evaluate -> promote/skip
- model gate: плохая модель не попадает в `champion`
- **MDD: Да**
- H0: `mean_improved >= mean_existing`
- H1: `mean_improved < mean_existing`
- test: Welch t-test, alternative=`less`, alpha=`0.05`
- p-value: `0.00000000`
- decision: heavy feature-compute -> batch preprocessing + feature store/cache
- latency SLO: p95 `/score` < 500 ms [assumption from MDD mapping]

Evidence:

- `reports/mdd_test_result.md`
- `reports/mdd_latency_distribution.png`
- `notebooks/mdd_latency.ipynb`
- `adr/0001-latency-mdd-decision.md`

---

## 12. Управление проектом

- delivery split: b01..b12
- текущая ветка b12: final manifest / design notebook / README / evidence index / rubric mapping / sanitize
- deliverables: repo + service + manifest + SLI/SLO + ADR + evidence pack
- deadline: до устной защиты
- remaining P2: cloud VM deploy + public `/health` URL

Evidence:

- final README: `README.md`
- rubric: `reports/rubric_mapping.md`
- screenshots index: `screenshots/INDEX.md`
- sanitize: `reports/sanitize_report.md`

**Вывод:** ML-005 собран как homework-facing Level 2 package; cloud deploy остается отдельной финальной веткой.
