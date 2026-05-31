Generated at: 2026-05-31 23:00:58 MSK

# ADR 0001: latency MDD decision for cached NBO scoring

## Status

Accepted

## Context

Есть два синтетических набора latency для NBO scoring service:

- `data/reference_latency.csv` - existing path, request-time feature compute, n = `500000`
- `data/new_latency.csv` - improved path, cached precomputed top-N, n = `500000`

Метрика системная: latency сервиса `/score`, не accuracy модели. Existing-распределение около `3.5`, т.к. тяжелые фичи считаются в request path. Improved-распределение около `2.0`, т.к. API отдает предрасчитанный top-N из feature store/cache.

[assumption] единица latency = ms-proxy из ДЗ. Для SLO sanity в notebook использован множитель `150 ms` на 1 proxy-unit: improved p95 проходит `< 500 ms`, existing p95 не проходит.

## Decision

- H0: `mean_improved >= mean_existing` (improved не быстрее)
- H1: `mean_improved < mean_existing` (improved быстрее)
- chosen test: `Welch t-test`, alternative=`less`, порядок аргументов `ttest_ind(improved, existing, equal_var=False, alternative="less")`
- alpha: `0.05`
- p-value: `0.00000000`
- robustness test: `Mann-Whitney U`, alternative=`less`, p-value `0.00000000`
- decision rule: `p_value < alpha` -> H0 rejected, H1 accepted
- final architecture decision: перенести тяжелый feature-compute в batch preprocessing + feature store/cache; API `/score` отдает предрасчитанный top-N из кэша; держать p95 `/score` latency SLO `< 500 ms` (master TZ, section 6)

## Consequences

Плюсы:

- ниже p95/p99 latency
- предсказуемый SLA для scoring request path
- inference из кэша без live remote sync в request path

Минусы:

- freshness lag: кэш может стареть между batch refresh
- нужен DAG/data-freshness monitoring для batch features
- остается cache invalidation

Что мониторим дальше:

- p95/p99 latency `/score`
- долю stale cache
- data-freshness в DAG
