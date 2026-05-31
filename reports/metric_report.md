Generated at: 2026-05-31 22:44:22 MSK

# NBO offline metric report

- holdout_quarter: `2022Q1`
- k: `10`
- n_clients_eval: `5555`
- n_products: `25`
- model_source: `b03_model_artifact`

## challenger vs champion

| metric | challenger | champion | uplift_abs |
|---|---:|---:|---:|
| precision_at_10 | 0.003204 | 0.003258 | -0.000054 |
| recall_at_10 | 0.474667 | 0.482667 | -0.008000 |
| map_at_10 | 0.145997 | 0.162301 | -0.016304 |
| ndcg_at_10 | 0.221149 | 0.235570 | -0.014421 |
| hit_rate_at_10 | 0.032043 | 0.032583 | -0.000540 |
| per_product_auc_macro | 0.802959 | 0.541206 | 0.261753 |

## uplift

- precision_at_10_abs: `-0.000054`
- hit_rate_at_10_abs: `-0.000540`
- policy: b04 writes absolute deltas only; b07 owns gate threshold.

## coverage

- scorable_share: `1.000000`
- not_scorable_share: `0.000000`
- no-INN / NOT_SCORABLE rows are excluded from quality metric denominators.

## denominators

- precision@10 / hit-rate@10: all scorable rows with non-empty scores.
- recall@10 / MAP@10 / NDCG@10: scorable rows with at least one positive holdout label.
- per-product ROC-AUC: only products with both classes in holdout; one-class products are `null` in JSON.

## calibration

- calibration_gap: `0.486151`

## per-segment hit-rate@10

| segment | n_clients | hit_rate_at_10 |
|---|---:|---:|
| SEG_0 | 1570 | 0.038217 |
| SEG_1 | 1103 | 0.037171 |
| SEG_2 | 947 | 0.030623 |
| SEG_3 | 612 | 0.014706 |
| SEG_4 | 573 | 0.020942 |
| SEG_5 | 451 | 0.044346 |
| SEG_6 | 299 | 0.023411 |

## notes

- min_support: `50`; small product support can make per-product AUC noisy.
- auc_products_used: `25`.

**Вывод:** challenger precision@10 is below champion; b05/b07 should read `metric_report.json` and apply downstream gate policy.
