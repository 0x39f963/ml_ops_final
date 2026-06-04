# b02 - проверка feature store

лог по фиче-слою b02: pit-safe фичи, стабильность feature_list и его hash, проверки на утечку.

## парсинг

команда:

```bash
python3 -c "import ast; ast.parse(open('src/features.py').read()); print('parse ok')"
```

вывод:

```text
parse ok
```

## pytest

команда:

```bash
pytest tests/test_features.py -v
```

вывод:

```text
tests/test_features.py::test_build_returns_matrix PASSED
tests/test_features.py::test_feature_list_stable PASSED
tests/test_features.py::test_pit_assert_passes PASSED
tests/test_features.py::test_pit_assert_rejects_unfiltered_future_rows PASSED
tests/test_features.py::test_monetary_proxy_counts_non_null_money_events PASSED
tests/test_features.py::test_no_future_leak PASSED
tests/test_features.py::test_column_order_matches_feature_list PASSED
tests/test_features.py::test_get_features_parity PASSED
8 passed in 0.41s
```

## сборка и запись в feature store

команда:

```bash
python3 -c "from src.features import build_and_store; print(build_and_store(['2025Q3','2025Q4']))"
```

вывод:

```text
data/feature_store
```

## начало feature_list

команда:

```bash
python3 -c "import json; d=json.load(open('artifacts/feature_list.json')); print(d['version'], d['hash']); [print(f) for f in d['features'][:12]]"
```

вывод:

```text
1 b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a
{'name': 'seg_SEG_0', 'dtype': 'int8'}
{'name': 'seg_SEG_1', 'dtype': 'int8'}
{'name': 'seg_SEG_2', 'dtype': 'int8'}
{'name': 'seg_SEG_3', 'dtype': 'int8'}
{'name': 'seg_SEG_4', 'dtype': 'int8'}
{'name': 'seg_SEG_5', 'dtype': 'int8'}
{'name': 'seg_SEG_6', 'dtype': 'int8'}
{'name': 'recency_quarters', 'dtype': 'int64'}
{'name': 'freq_events_total', 'dtype': 'int64'}
{'name': 'freq_events_last_4q', 'dtype': 'int64'}
{'name': 'monetary_proxy_count', 'dtype': 'int64'}
{'name': 'affinity_fam_software_box', 'dtype': 'int64'}
```

## стабильность hash

проверяю, что hash feature_list не зависит от сида данных - на двух разных сидах должен совпасть.

команда:

```bash
python3 - <<'PY'
from src.features import build_features, compute_feature_list, quarter_to_cutoff_end
from src.gen_synthetic import build_synthetic
for seed in (101, 202):
    events = build_synthetic(rows=250, seed=seed, box_share=0.85, pseudo_share=0.22, empty_client_share=0.0)
    clients = sorted(events['client_id'].dropna().unique())[:5]
    matrix = build_features([(client, '2025Q4') for client in clients], quarter_to_cutoff_end('2025Q4'), events=events)
    print(seed, compute_feature_list(matrix)['hash'])
PY
```

вывод:

```text
101 b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a
202 b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a
```

## проверки на утечку

команды:

```bash
git status --porcelain | grep -E '\.parquet$' || true
grep -rn "revenue" src/features.py || true
grep -Rni "min.support\|min_support" src/features.py tests/test_features.py || true
make leak-check
```

вывод:

```text
# parquet status: empty
411:    if "revenue_proxy" in client_events.columns:
412:        # The upstream revenue_proxy field is sparse; count presence, not amount.
413:        money_events = client_events.loc[client_events["revenue_proxy"].notna()]
# min-support grep: empty
checking gitignore gates
checking tracked and staged file list
leak-check passed
```

## b02-fix f1: денежный прокси-признак

проверяю, что monetary_proxy_count считается как число событий с непустым revenue_proxy (а не как полная частота событий), и что значение совпадает с честным pit-расчетом.

команда:

```bash
python3 -c "from src.features import build_and_store; print(build_and_store(['2024Q4','2025Q3','2025Q4']))"
```

вывод:

```text
data/feature_store
```

команда:

```bash
python3 - <<'PY'
import pandas as pd
from src.data_wrappers import load_events
from src.features import quarter_to_cutoff_end
cutoff = quarter_to_cutoff_end('2024Q4')
features = pd.read_parquet('data/feature_store/quarter=2024Q4/part.parquet')
events = load_events()
events['ts'] = pd.to_datetime(events['ts'])
pit = events.loc[events['ts'] <= cutoff].copy()
expected = pit.loc[pit['revenue_proxy'].notna()].groupby('client_id').size()
actual = features.set_index('client_id')['monetary_proxy_count']
expected_aligned = actual.index.to_series().map(expected).fillna(0).astype('int64')
corr = features['monetary_proxy_count'].corr(features['freq_events_total'])
print('rows', len(features))
print('corr', round(float(corr), 6))
print('equal_expected', bool(actual.reset_index(drop=True).equals(expected_aligned.reset_index(drop=True))))
print('same_as_freq', bool(features['monetary_proxy_count'].equals(features['freq_events_total'])))
assert corr < 1.0
assert actual.reset_index(drop=True).equals(expected_aligned.reset_index(drop=True))
assert not features['monetary_proxy_count'].equals(features['freq_events_total'])
PY
```

вывод:

```text
rows 11976
corr 0.294218
equal_expected True
same_as_freq False
```

примечание: feature_list.hash по задумке не меняется - он считается только по именам фич, их типам и порядку. сам json при этом пересобрался.
