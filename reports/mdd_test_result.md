Generated at: 2026-05-31 23:00:58 MSK

# MDD latency test

- metric: `latency` (ms-proxy)
- n existing / n improved: `500000` / `500000`
- seed: `42`
- existing mean / median: `3.499797` / `3.499340`
- improved mean / median: `2.000281` / `2.000117`
- existing p95 / p99: `4.157986` / `4.432341`
- improved p95 / p99: `2.658702` / `2.929972`
- [assumption] SLO sanity: `1 ms-proxy = 150 ms`, improved p95 `398.81 ms` -> pass `< 500 ms`, existing p95 `623.70 ms` -> fail
- H0: `mean_improved >= mean_existing`
- H1: `mean_improved < mean_existing`
- test: `Welch t-test`, alternative=`less`
- alpha: `0.05`
- statistic: `-1873.490`
- p_value: `0.00000000`
- robustness test: `Mann-Whitney U`, alternative=`less`
- robustness statistic: `1.0011e9`
- robustness p_value: `0.00000000`
- decision: `move heavy feature compute to batch + serve precomputed top-N from cache`
- TODO-stub: `b01/b09` должны подтвердить MDD deps (`numpy` / `scipy` / `matplotlib` / `pandas`) в requirements; b10 requirements не редактирует

**Вывод:** p-value ниже alpha -> improved быстрее статистически значимо, решение принято.
