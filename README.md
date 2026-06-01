# ML Ops final - сервис next-best-offer (NBO)

финальный проект по курсу "развертывание ml-моделей".

за основу взял рабочую модель из проекта на работе (рекомендация продуктов клиенту по истории) и собрал вокруг нее mlops-обвязку уровня 2 по требованиям дз: данные -> фичи -> обучение -> оценка -> registry -> сервинг -> мониторинг.

домен обезличенный: вендор b2b-софта (продажи / продления лицензий). задача: по клиенту (`client_id`) на дату вернуть топ-10 продуктов, которые он скорее всего купит / продлит в следующем квартале (Q+1).

---

## про данные и модель

саму обученную модель и реальные данные в репозиторий положить не могу, nda. поэтому в git уходит только синтетика + код, а работу сервиса показываю на скринах с localhost.

- в репо лежит маленький синтетический сэмпл [data/sample_synth.parquet](data/sample_synth.parquet), на нем все крутится локально / в ci.
- реальные parquet / `model.pkl` / `mlruns` / `.env` держу на localhost, закрыты через [.gitignore](.gitignore).
- обезличивание: продукты = `PROD_01..PROD_39`, сегменты = `SEG_0..SEG_6`, клиент = `client_id` (хэш, не инн).
- свой `make leak-check` гоняю перед каждым пушем: проверяет gitignore-гейты + ищет в файлах id-подобные номера / сырые имена продуктов.

---

## структура

```text
ml005/
|-- README.md
|-- requirements.txt
|-- docker-compose.yml        # mlflow; остальные сервисы в инфра-части
|-- Makefile                  # data / test / up / down / leak-check
|-- .env.example
|-- src/
|   |-- gen_synthetic.py      # генератор синтетики (для git/ci)
|   |-- data_wrappers.py      # доступ к локальным данным (реальные - вне git)
|   |-- features.py           # pit-safe фичи + feature store
|   |-- labels.py             # таргет на Q+1
|   |-- train.py              # champion (popularity) + challenger (supervised)
|   |-- evaluate.py           # офлайн-метрики на holdout
|   `-- registry.py           # mlflow alias champion/challenger
|-- artifacts/
|   `-- feature_list.json     # контракт фич (порядок + hash), общий для train/serve
|-- notebooks/
|   `-- mdd_latency.ipynb     # mdd по latency
|-- adr/
|   `-- 0001-latency-mdd-decision.md
|-- reports/                  # верификационные логи + метрики (без реальных данных)
|-- tests/                    # pytest (features / train / eval / registry)
|-- data/                     # только sample_synth.parquet (синтетика)
`-- dags/  infra/  monitoring/  demo/  screenshots/   # сервинг / инфра / мониторинг / demo / скрины
```

---

## бизнес-задача + метрика

- по клиенту отдаю топ-10 продуктов с вероятностью покупки / продления в Q+1.
- ранжирую на уровне продукта (~39 штук). на уровне семейства их всего 6 + один доминирует ~85%, "топ-10" там вырождается в одно популярное.
- главная бизнес-метрика: **hit-rate@10** (доля клиентов, у кого хотя бы 1 из топ-10 реально сбылась в Q+1).
- ml-прокси к ней: precision@10 / recall@10 / map@10 / ndcg@10 + uplift над popularity-бейзлайном.
- ранжирую по вероятности. денежные поля - это прокси, не реальная выручка, за выручку их нигде не выдаю.

---

## пайплайн

```text
events -> features (pit cutoff) -> train: champion + challenger -> evaluate (holdout Q_t+1) -> registry (alias)
```

### фичи

- ключ строки = (`client_id`, `quarter`).
- фичи считаются строго до конца квартала (point-in-time), будущее в фичи не течет (есть тест на это).
- порядок и набор фич зафиксирован в `feature_list.json` + schema-hash. этот hash один на проект, его же сверяет сервинг (parity train/serve).

### обучение: champion + challenger

- champion = popularity + сегментный приор (со сглаживанием) + co-occurrence. простой объяснимый бейзлайн.
- challenger = supervised multi-label, старт logreg one-vs-rest, цель lightgbm (per-product, с балансом классов).
- temporal split: учу на кварталах <= Q_t, проверяю на Q_t+1. сид фиксирован, воспроизводимо.
- строки без инн / pseudo-инн из обучения выкидываю (помечаю not_scorable).
- gate (регистрировать новую модель или нет) живет в dag. train сам по себе только обучает + считает sanity-метрики.

### оценка

- метрики на honest holdout (Q_t+1): precision@10 / recall@10 / map@10 / ndcg@10 / hit-rate@10 + per-product auc.
- challenger сравниваю с champion, считаю uplift (абсолютный + относительный).
- отчеты: [reports/metric_report.md](reports/metric_report.md) (человеку) + reports/metric_report.json (для gate).
- на синтетике сигнал слабый, поэтому абсолютные числа маленькие. синтетика нужна только чтобы пайплайн крутился, на реальных данных метрики другие.

### mlflow registry

- модель версионируется в mlflow, переключение champion/challenger через alias (без хардкода версий).
- `promote(version)` выводит в прод (после gate), `rollback()` откатывает на прошлую версию. это и есть "вывод плохой модели через переключение трафика".
- байты модели лежат локально (`model.pkl`, вне git), registry хранит версию / hash / метрики / alias.

запуск mlflow локально:

```bash
docker compose up -d mlflow
# ui: http://localhost:15000
python -m src.registry --show
```

### сервинг (api)

fastapi-сервис поверх champion-модели (читается по mlflow alias, без хардкода версии).

- `GET /health` - статус, версия модели, data_cutoff.
- `POST /score` - по client_id на дату отдает топ-10 продуктов `{product, p, decision, confidence}` + caveats.
- `POST /batch-score` - то же списком.
- `GET /model-info` - версия / метрики / feature_list_hash.
- `GET /metrics` - prometheus-формат (latency, число запросов, ошибки, распределение score).
- parity: фичи считаю тем же кодом и тем же feature_list.json, что train. в request-path нет похода за свежими данными (тяжелый расчет вынесен в feature store).
- честный not_scorable: клиент без инн / без записи -> score=null, без выдуманного топ-10.

```bash
docker compose up -d --build nbo-api   # http://localhost:18000/health
```

### переобучение (airflow dag)

`nbo_retrain_pipeline` - континуальное переобучение с гейтом по метрике (это и есть "вывод плохой модели через переключение трафика").

- цепочка: `wait_for_batch` (file/s3 sensor) -> `validate_data` -> `build_features` -> `train` -> `evaluate` -> `compare_with_champion` -> `register_model` / `skip_deploy` -> `finish`.
- gate: `precision@10_new >= champion и >= порога` -> регистрируем + промоутим challenger в champion (alias-switch). иначе skip, champion не трогаем.
- validate реально падает (raise) на битой схеме / null / out-of-range, не пускает обучение дальше.
- обучение живет только в dag, не в ci.
- dag парсится и без установленного airflow (shim), чтобы ci/тесты не тянули airflow и не запускали обучение.

```bash
docker compose -f docker-compose.yml -f dags/airflow_compose_snippet.yml up -d airflow   # ui http://localhost:18080
```

### мониторинг (prometheus + grafana + evidently)

- prometheus скрейпит `nbo-api:8000/metrics` + node-exporter, держит alert-правила (p95 latency, error-rate).
- grafana авто-провижинит дашборд `nbo_overview`: p95/p99 latency, error-rate, rps, drift share.
- evidently/drift: считаю data drift + psi на выходах пайплайна, пишу html-отчет + `nbo_drift.prom` для node-exporter (живая drift-метрика). вызывается standalone и шагом из dag.
- sli/slo на 3 уровнях (технический / модель-данные / бизнес) с порогами и incident-action: [docs/sli_slo.md](docs/sli_slo.md). пороги пока [assumption] до baseline.

```bash
docker compose up -d prometheus grafana node-exporter   # grafana http://localhost:3000 (admin/admin), prometheus http://localhost:9090
```

---

## mdd / adr (latency)

проверяю гипотезу про скорость ответа сервиса на двух распределениях latency (старая схема vs улучшенная с кэшом).

- H0: improved не быстрее. H1: improved быстрее.
- тест: welch t-test (alternative=less) + mann-whitney u как робастность. alpha = 0.05.
- p-value ~ 0, H0 отклоняю.
- решение в adr: тяжелый расчет фич вынести в batch + feature store/cache, api отдает предрасчитанный топ-N, держим p95 `/score` < 500 ms.

файлы: [reports/mdd_test_result.md](reports/mdd_test_result.md), [reports/mdd_latency_distribution.png](reports/mdd_latency_distribution.png), [adr/0001-latency-mdd-decision.md](adr/0001-latency-mdd-decision.md).

большие latency-csv (по 500k строк) в git не кладу, они регенерятся ноутбуком.

---

## sli/slo

| уровень | sli | slo normal | critical |
|---|---|---|---|
| технический | p95 `/score` latency | `< 500 ms` | `> 800 ms` |
| технический | `/health` доступность | `>= 99%` | `< 97%` |
| модель/данные | precision@10 vs champion | `>= champion + порог` | `< champion` |
| модель/данные | drift (psi / evidently) | ниже порога | выше 2x порога |
| бизнес | hit-rate@10 | `>= baseline` | `-25%` |

полную таблицу на 3 уровнях довешу вместе с мониторингом.

---

## как запустить локально

```bash
# окружение
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# синтетические данные
make data

# тесты
.venv/bin/python -m pytest -q

# проверка на утечку (должно быть зелено)
make leak-check

# обучить (на синтетике)
.venv/bin/python -m src.train --quarter 2021Q4

# офлайн-оценка
.venv/bin/python -m src.evaluate

# mlflow registry
docker compose up -d mlflow   # ui http://localhost:15000
```

---

## в разработке

- iac terraform + ci/cd (github actions: lint / tests / terraform plan)
- demo ui: ввод client_id -> топ-10 предсказанных продуктов
- манифест зрелости (level 2) + финальная сборка + скрины (docker ps healthy, /health 200)
- деплой в облако (одна vm, перед защитой)
