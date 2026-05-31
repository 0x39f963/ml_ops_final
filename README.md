Generated at: 2026-05-31 20:37:33 MSK

# ML-005 Next-Best-Offer Service

## О проекте

Учебный Level-2 MLOps-проект для анонимизированного домена `B2B software license vendor`.
Цель - по `client_id` и `reference_date` вернуть top-10 продуктов на следующий квартал Q+1.
В публичном репозитории используются только обезличенные имена: `client_id`, `PROD_01..PROD_39`, `SEG_0..SEG_6`.

## Anti-leak

В git попадают только код-обертки, синтетика, документация и будущие evidence-артефакты.
Реальные parquet, локальные модели, MLflow runs и `.env` остаются local-only и закрыты `.gitignore`.
Единственный parquet, разрешенный в git: `data/sample_synth.parquet`.
Дополнительная проверка имени закрытого домена запускается так: `FORBIDDEN_COMPANY_NAME='local value' make leak-check`.

## Quickstart

```bash
cp .env.example .env
make data
make leak-check
```

`make data` создает synthetic stub на 40000 строк с client-affinity и next-quarter recurrence для boot/train smoke.

TODO b02+: feature layer, adaptive min-support for synthetic, train/eval, registry, API, DAG, monitoring, infra, demo UI, manifest.

## Структура

```text
ml005/
  src/              # data wrappers and synthetic generator
  data/             # synthetic stub only
  dags/             # TODO b07
  infra/            # TODO b09
  monitoring/       # TODO b08
  adr/              # TODO b10
  notebooks/        # TODO b10/b12
  demo/             # TODO b11
  models/           # local-only artifacts, ignored except .gitkeep
  reports/          # text evidence
  screenshots/      # image evidence
  tests/            # smoke/unit tests
```

## Evidence placeholders

- `screenshots/` - TODO b03..b11 evidence screenshots.
- `reports/` - TODO command logs and metric reports.
- `manifest.md` - TODO b12 final assembly.
