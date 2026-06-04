# b01 Follow-up F1-F4 Verification Log

## make data

Command:

```bash
make data
```

Output:

```text
python3 -m src.gen_synthetic --rows 40000 --out data/sample_synth.parquet
path=data/sample_synth.parquet
rows=40000
unique_client_id=12800
fam_box_share=0.8500
inn_is_pseudo_share=0.2200
products_recurrence_ge_15=39
next_quarter_positive_pairs=11332
```

## schema and recurrence check

Command:

```bash
python3 - <<'PY'
import pandas as pd
START_YEAR = 2019
df = pd.read_parquet('data/sample_synth.parquet')
events = df.loc[df.client_id != '', ['client_id', 'product', 'year', 'quarter']].drop_duplicates().copy()
events['q_idx'] = (events.year - START_YEAR) * 4 + events.quarter - 1
events = events.sort_values(['client_id', 'product', 'q_idx'])
events['recur'] = events.q_idx.sub(events.groupby(['client_id', 'product']).q_idx.shift()).eq(1)
per_product = events.loc[events.recur].groupby('product').size()
counts = df.groupby('client_id').size()
print(df.shape)
print(sorted(df.columns))
print(df['product'].nunique(), df['segment'].nunique(), df['product_family'].nunique())
print(round((df.product_family == 'FAM_BOX').mean(), 4), round(df.inn_is_pseudo.mean(), 4), round(df.revenue_proxy.isna().mean(), 4))
print(int((per_product >= 15).sum()), int(events.recur.sum()), round((counts <= 3).mean(), 4), int(counts.max()))
PY
```

Output:

```text
(40000, 10)
['client_id', 'inn_is_pseudo', 'lifecycle_role', 'product', 'product_family', 'quarter', 'revenue_proxy', 'segment', 'ts', 'year']
39 7 6
0.85 0.22 0.92
39 11332 0.7111 37
```

## wrapper smoke

Command:

```bash
python3 -c "import src.data_wrappers as w; print('import ok'); print(w.load_events('2020-12-31').shape); print(w.load_segment_timeline('2020-12-31').shape); print(w.load_scoring_registry().shape); print(w.normalize_client_id(' C 123 '))"
```

Output:

```text
import ok
(6518, 10)
(6518, 5)
(12800, 5)
C123
```

## generator smoke

Command:

```bash
python3 -m src.gen_synthetic --rows 100 --out /tmp/_smoke.parquet
```

Output:

```text
path=/tmp/_smoke.parquet
rows=100
unique_client_id=32
fam_box_share=0.8500
inn_is_pseudo_share=0.2200
products_recurrence_ge_15=0
next_quarter_positive_pairs=25
```

## sample size

Command:

```bash
du -h data/sample_synth.parquet
```

Output:

```text
724K	data/sample_synth.parquet
```

## compile smoke

Command:

```bash
python3 -m compileall -q src
```

Output:

```text

```

## leak-check

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

Exit code: 0.

## leak-check with name guard configured

Command:

```bash
FORBIDDEN_COMPANY_NAME="$(printf 'local-check-%s' "$RANDOM")" make leak-check
```

Output:

```text
checking gitignore gates
checking tracked and staged file list
checking FORBIDDEN_COMPANY_NAME
leak-check passed
```

Exit code: 0.

## parent repo ignore guard

Command:

```bash
git status --short --untracked-files=normal | rg 'ml005|\.gitignore' || true
```

Output:

```text
?? .gitignore
```

Note: parent repo now reports the root `.gitignore` change only; `ml005/` is ignored and is no longer shown as an untracked nested repo.
