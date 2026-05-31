Generated at: 2026-05-31 22:03:27 MSK
Updated at: 2026-05-31 22:24:55 MSK

## b03 training verification log

## cli train

Command:

```bash
python3 -m src.train --quarter 2021Q4 --backend logreg
```

Output summary:

```text
MLflow logging skipped: MLFLOW_TRACKING_URI is empty.
model_path: /home/x39963/web/niki/mo-dz/ml005/models/model.pkl
meta_path: /home/x39963/web/niki/mo-dz/ml005/models/meta.json
metrics:
  n_train_rows: 32814
  n_holdout_rows: 5555
  n_products_catalog: 25
  macro_auc_challenger: 0.802959
  seed: 42
  backend: logreg
  min_support: 50
run_id: nbo_train_20260531_190439
```

## model dir

Command:

```bash
ls -la models
```

Output:

```text
meta.json
model.pkl
product_catalog.json
```

## meta keys and load

Command:

```bash
python3 -c "import json,joblib; m=json.load(open('models/meta.json')); print(sorted(m.keys())); a=joblib.load('models/model.pkl'); print(sorted(a.keys()), a['active'])"
```

Output:

```text
['backend', 'created_at', 'feature_list', 'feature_list_hash', 'lib_versions', 'metrics', 'min_support', 'product_catalog', 'seed']
['active', 'challenger', 'champion'] champion
```

## gitignore gate

Command:

```bash
git check-ignore models/model.pkl models/meta.json models/product_catalog.json
```

Output:

```text
models/model.pkl
models/meta.json
models/product_catalog.json
```

## status

Command:

```bash
git status --porcelain
```

Output:

```text
 M .env.example
 M .gitignore
?? artifacts/
?? reports/b02_feature_store_verification_log.md
?? reports/train_run.json
?? src/features.py
?? src/labels.py
?? src/registry.py
?? src/train.py
?? tests/test_features.py
?? tests/test_train_smoke.py
```

Note: `.gitignore`, `artifacts/`, `src/features.py`, `tests/test_features.py`,
and `reports/b02_feature_store_verification_log.md` are b01/b02 dirty state
observed before b03 edits.

## tests

Command:

```bash
python3 -m pytest tests/test_features.py tests/test_train_smoke.py -q
```

Output:

```text
11 passed in 13.22s
```

Command:

```bash
python3 -m compileall -q src tests
```

Output:

```text
no output, exit code 0
```

## determinism

Command:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from src.train import train_model
first = train_model('2021Q4', backend='logreg', min_support=50, seed=42)
meta_1 = json.loads(Path(first['meta_path']).read_text())
second = train_model('2021Q4', backend='logreg', min_support=50, seed=42)
meta_2 = json.loads(Path(second['meta_path']).read_text())
print('same_feature_list_hash', meta_1['feature_list_hash'] == meta_2['feature_list_hash'])
print('same_product_catalog', meta_1['product_catalog'] == meta_2['product_catalog'])
print('catalog_size', len(meta_2['product_catalog']))
PY
```

Output:

```text
MLflow logging skipped: MLFLOW_TRACKING_URI is empty.
MLflow logging skipped: MLFLOW_TRACKING_URI is empty.
same_feature_list_hash True
same_product_catalog True
catalog_size 25
```

## leak check

Command:

```bash
make leak-check
```

Output:

```text
checking gitignore gates
checking tracked and staged file list
leak-check passed
```

## b03-fix tests

Command:

```bash
python3 -m pytest tests/test_features.py tests/test_train_smoke.py -q
```

Output:

```text
13 passed in 13.29s
```

## b03-fix feature hash invariance

Command:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from src import features, train
result = train.train_model('2021Q4', backend='logreg', min_support=50, seed=42)
meta = json.loads(Path(result['meta_path']).read_text())
before = meta['feature_list_hash']
store = features.build_and_store(['2024Q4'])
feature_list = json.loads(Path('artifacts/feature_list.json').read_text())
after = train.feature_list_hash(feature_list)
print('store', store)
print('meta_hash', before)
print('feature_list_hash_field', feature_list['hash'])
print('recomputed_hash', after)
print('same_after_regen', before == after)
print('equals_schema_hash', after == feature_list['hash'])
PY
```

Output:

```text
MLflow logging skipped: MLFLOW_TRACKING_URI is empty.
store /home/x39963/web/niki/mo-dz/ml005/data/feature_store
meta_hash b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a
feature_list_hash_field b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a
recomputed_hash b29e3f6fd325627e3b77475f1c0148ce298fa2a4c68d8cc2f8af75961ab4c98a
same_after_regen True
equals_schema_hash True
```

## b03-fix co-occurrence activation

Command:

```bash
python3 - <<'PY'
import pandas as pd
from src.train import ChampionModel, owned_products_from_events

events = pd.DataFrame([
    {'client_id': 'C1', 'ts': '2024-01-15', 'product': 'PROD_02', 'lifecycle_role': 'primary', 'inn_is_pseudo': False},
    {'client_id': 'C1', 'ts': '2024-02-15', 'product': 'PROD_01', 'lifecycle_role': 'special', 'inn_is_pseudo': False},
    {'client_id': 'C1', 'ts': '2024-07-15', 'product': 'PROD_03', 'lifecycle_role': 'primary', 'inn_is_pseudo': False},
])
champion = ChampionModel(
    catalog=['PROD_01', 'PROD_02', 'PROD_03'],
    global_scores={'PROD_01': 0.2, 'PROD_02': 0.05, 'PROD_03': 0.1},
    segment_scores={'SEG_0': {'PROD_01': 0.2, 'PROD_02': 0.05, 'PROD_03': 0.1}},
    co_scores={'PROD_02': {'PROD_01': 0.0, 'PROD_03': 0.95}},
    co_weight=0.9,
)
owned = owned_products_from_events('C1', '2024Q1', events=events)
base = champion.rank({'seg_SEG_0': 1}, top_n=3)
with_owned = champion.rank({'seg_SEG_0': 1, 'owned_products': owned}, top_n=3)
print('owned', owned)
print('base_top1', base[0])
print('with_owned_top1', with_owned[0])
print('co_activated', base[0][0] != with_owned[0][0])
PY
```

Output:

```text
owned ['PROD_02']
base_top1 ('PROD_01', 0.2)
with_owned_top1 ('PROD_03', 0.865)
co_activated True
```

## b03-fix leak check

Command:

```bash
git check-ignore models/model.pkl models/meta.json
make leak-check
```

Output:

```text
models/model.pkl
models/meta.json
checking gitignore gates
checking tracked and staged file list
leak-check passed
```
