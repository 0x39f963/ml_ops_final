# ML Ops final - сервис next-best-offer (NBO)

финальный проект по курсу "развертывание ml-моделей".

цель не просто обучить модель, а собрать ml-систему уровня 2 (mlops): данные -> фичи -> обучение -> оценка -> registry -> сервинг -> мониторинг. часть уже готова, часть в работе (см. статус ниже).

домен обезличенный: вендор b2b-софта (продажи / продления лицензий). задача: по клиенту (`client_id`) на дату вернуть топ-10 продуктов, которые он скорее всего купит / продлит в следующем квартале (Q+1).

---

## про данные (важно)

- реальные данные и обученную модель в git я НЕ кладу. только синтетика + код-обертки.
- в репо лежит маленький синтетический сэмпл [data/sample_synth.parquet](data/sample_synth.parquet), на нем все запускается локально / в ci.
- реальные parquet / `model.pkl` / `mlruns` / `.env` - только на localhost, закрыты [.gitignore](.gitignore).
- обезличивание: продукты = `PROD_01..PROD_39`, сегменты = `SEG_0..SEG_6`, клиент = `client_id` (хэш, не инн).
- есть свой `make leak-check` - гоняет gitignore-гейты + ищет в файлах id-подобные номера / сырые имена продуктов. перед каждым пушем зеленый.

---

## что готово / что в работе

| блок | статус | где |
|---|---|---|
| scaffold + анти-утечка | готово | [.gitignore](.gitignore), [Makefile](Makefile) |
| синтетика + обертки данных | готово | [src/gen_synthetic.py](src/gen_synthetic.py), [src/data_wrappers.py](src/data_wrappers.py) |
| feature store (pit-safe) | готово | [src/features.py](src/features.py), [artifacts/feature_list.json](artifacts/feature_list.json) |
| label + train (champion/challenger) | готово | [src/labels.py](src/labels.py), [src/train.py](src/train.py) |
| офлайн-оценка (precision@10 / map / ndcg / hit-rate) | готово | [src/evaluate.py](src/evaluate.py), [reports/metric_report.md](reports/metric_report.md) |
| mlflow registry (champion/challenger) | готово | [src/registry.py](src/registry.py), [docker-compose.yml](docker-compose.yml) |
| mdd + adr (latency) | готово | [notebooks/mdd_latency.ipynb](notebooks/mdd_latency.ipynb), [adr/0001-latency-mdd-decision.md](adr/0001-latency-mdd-decision.md) |
| serving api (fastapi /score /health) | в работе | скоро выложу |
| retraining dag (airflow) | в работе | скоро выложу |
| мониторинг (prometheus + grafana + evidently) | в работе | скоро выложу |
| iac (terraform) + ci/cd | в работе | скоро выложу |
| demo ui (ввел client_id -> топ-10) | в работе | скоро выложу |
| манифест + финальная сборка + скрины | в работе | скоро выложу |

---

## структура

```text
ml005/
|-- README.md
|-- requirements.txt
|-- docker-compose.yml        # пока только mlflow, остальное добавлю в инфра-части
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
|   `-- mdd_latency.ipynb      # mdd по latency
|-- adr/
|   `-- 0001-latency-mdd-decision.md
|-- reports/                  # верификационные логи + метрики (без реальных данных)
|-- tests/                    # pytest (features / train / eval / registry)
|-- data/                     # только sample_synth.parquet (синтетика)
|-- dags/  infra/  monitoring/  demo/  screenshots/   # пока заглушки, заполню по ходу
```

---

## бизнес-задача + метрика

- по клиенту отдаем топ-10 продуктов с вероятностью покупки / продления в Q+1.
- ранжируем на уровне продукта (~39 штук). на уровне семейства их всего 6 + один доминирует ~85%, т.е. "топ-10" там смысла нет.
- главная бизнес-метрика: **hit-rate@10** (доля клиентов, у кого хотя бы 1 из топ-10 реально сбылась в Q+1).
- ml-прокси к ней: precision@10 / recall@10 / map@10 / ndcg@10 + uplift над popularity-бейзлайном.
- ценность только в вероятности, не в деньгах (денежные поля - прокси, не реальная выручка), за выручку это нигде не выдаю.

---

## пайплайн (что уже работает)

```text
events -> features (pit cutoff) -> train: champion + challenger -> evaluate (holdout Q_t+1) -> registry (alias)
```

### фичи

- ключ строки = (`client_id`, `quarter`).
- фичи считаются строго до конца квартала (point-in-time), будущее в фичи не течет (есть тест на это).
- порядок и набор фич зафиксирован в `feature_list.json` + schema-hash. этот hash один на проект, его же сверяет сервинг (parity train/serve).

### обучение: champion + challenger

- champion = popularity + сегментный приор (со сглаживанием) + co-occurrence. простой и объяснимый бейзлайн.
- challenger = supervised multi-label, старт logreg one-vs-rest, цель lightgbm (per-product, с балансом классов).
- temporal split: учим на кварталах <= Q_t, проверяем на Q_t+1. сид фиксирован -> воспроизводимо.
- строки без инн / pseudo-инн из обучения выкидываю (помечаю not_scorable).
- сам gate (регистрировать новую модель или нет) будет в dag. train пока только обучает + считает sanity-метрики.

### оценка

- метрики на honest holdout (Q_t+1): precision@10 / recall@10 / map@10 / ndcg@10 / hit-rate@10 + per-product auc.
- challenger сравнивается с champion -> uplift (абсолютный + относительный).
- отчеты: [reports/metric_report.md](reports/metric_report.md) (человеку) + reports/metric_report.json (для gate).
- на синтетике сигнал слабый, поэтому абсолютные числа маленькие - это норм, синтетика нужна только чтобы пайплайн крутился. на реальных данных метрики другие.

### mlflow registry

- модель версионируется в mlflow, переключение champion/challenger через alias (без хардкода версий).
- `promote(version)` - в прод (после gate), `rollback()` - откат на прошлую версию. это и есть "вывод плохой модели через переключение трафика".
- байты модели лежат локально (`model.pkl`, вне git), а registry хранит версию / hash / метрики / alias.

запуск mlflow локально:

```bash
docker compose up -d mlflow
# ui: http://localhost:15000
python -m src.registry --show
```

---

## mdd / adr (latency)

проверяю гипотезу про скорость ответа сервиса на двух распределениях latency (старая схема vs улучшенная с кэшом).

- H0: improved не быстрее. H1: improved быстрее.
- тест: welch t-test (alternative=less) + mann-whitney u как робастность. alpha = 0.05.
- p-value ~ 0 -> H0 отклоняю.
- решение в adr: тяжелый расчет фич вынести в batch + feature store/cache, api отдает предрасчитанный топ-N, держим p95 `/score` < 500 ms.

файлы: [reports/mdd_test_result.md](reports/mdd_test_result.md), [reports/mdd_latency_distribution.png](reports/mdd_latency_distribution.png), [adr/0001-latency-mdd-decision.md](adr/0001-latency-mdd-decision.md).

большие latency-csv (по 500k строк) в git не кладу, они регенерятся ноутбуком.

---

## sli/slo (черновик, дополню)

пока коротко, полную таблицу на 3 уровнях довешу вместе с мониторингом.

| уровень | sli | slo normal | critical |
|---|---|---|---|
| технический | p95 `/score` latency | `< 500 ms` | `> 800 ms` |
| технический | `/health` доступность | `>= 99%` | `< 97%` |
| модель/данные | precision@10 vs champion | `>= champion + порог` | `< champion` |
| модель/данные | drift (psi / evidently) | ниже порога | выше 2x порога |
| бизнес | hit-rate@10 | `>= baseline` | `-25%` |

---

## в работе (скоро выложу)

- [ ] serving api на fastapi: `/health`, `/score` (топ-10 по client_id), `/model-info`, `/metrics`
- [ ] retraining dag в airflow: sensor -> validate -> features -> train -> evaluate -> gate -> register/skip
- [ ] мониторинг: prometheus + grafana + evidently (drift), полная таблица sli/slo
- [ ] iac terraform + ci/cd (github actions: lint / tests / terraform plan)
- [ ] demo ui: вводишь client_id -> видишь топ-10 предсказанных продуктов
- [ ] манифест зрелости (level 2) + финальная сборка + скрины (docker ps healthy, /health 200 и т.д.)
- [ ] деплой в облако (одна vm, перед защитой)

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

## итог (на сейчас)

- [x] чистый репо, синтетика-only, анти-утечка работает
- [x] pit-safe фичи + контракт feature_list (parity train/serve)
- [x] champion (popularity) + challenger (supervised) + temporal split
- [x] офлайн-метрики на holdout + uplift
- [x] mlflow registry с champion/challenger + promote/rollback
- [x] mdd по latency + adr с решением
- [ ] api / dag / мониторинг / iac / demo / манифест - в работе
- [ ] облачный деплой - перед защитой

**Итого:** ядро ml-системы (данные -> фичи -> обучение -> оценка -> registry) собрано и проверено тестами. дальше навешиваю сервинг + оркестрацию + мониторинг + инфру, чтобы добить до полного level 2.
