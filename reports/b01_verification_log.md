# b01 Verification Log

This is the initial b01 scaffold log. Current follow-up evidence for F1-F4
and the 40000-row synthetic stub is in
`reports/b01_followup_f1_f4_verification_log.md`.

## make data

Command:

```bash
make data
```

Output:

```text
python3 -m src.gen_synthetic --rows 5000 --out data/sample_synth.parquet
path=data/sample_synth.parquet
rows=5000
unique_client_id=2750
fam_box_share=0.8500
inn_is_pseudo_share=0.2200
```

## smoke generator

Command:

```bash
python3 -m src.gen_synthetic --rows 100 --out /tmp/_smoke.parquet
```

Output:

```text
path=/tmp/_smoke.parquet
rows=100
unique_client_id=55
fam_box_share=0.8500
inn_is_pseudo_share=0.2200
```

## import wrapper

Command:

```bash
python3 -c "import src.data_wrappers; print('ok')"
```

Output:

```text
ok
```

## schema check

Command:

```bash
python3 -c "import pandas as pd; df=pd.read_parquet('data/sample_synth.parquet'); print(df.shape); print(sorted(df.columns)); print((df.product_family=='FAM_BOX').mean()); print(df.inn_is_pseudo.mean())"
```

Output:

```text
(5000, 10)
['client_id', 'inn_is_pseudo', 'lifecycle_role', 'product', 'product_family', 'quarter', 'revenue_proxy', 'segment', 'ts', 'year']
0.85
0.22
```

## wrapper cutoff smoke

Command:

```bash
python3 -c "from src.data_wrappers import load_events, normalize_client_id; df=load_events('2020-12-31'); print(df.shape); print(normalize_client_id(' C 123 '))"
```

Output:

```text
(1190, 10)
C123
```

## compile smoke

Command:

```bash
python3 -m compileall -q src
```

Output:

```text

```

## sample size

Command:

```bash
du -h data/sample_synth.parquet
```

Output:

```text
112K	data/sample_synth.parquet
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

## test

Command:

```bash
make -C /home/x39963/web/niki/mo-dz/ml005 test
```

Output:

```text
no tests yet
```

## git status

Command:

```bash
git status --short
```

Output:

```text
A  .env.example
A  .gitignore
A  Makefile
A  README.md
A  adr/.gitkeep
A  dags/.gitkeep
A  data/.gitkeep
A  data/sample_synth.parquet
A  demo/.gitkeep
A  infra/.gitkeep
A  models/.gitkeep
A  monitoring/.gitkeep
A  notebooks/.gitkeep
A  reports/.gitkeep
A  reports/b01_verification_log.md
A  requirements.txt
A  screenshots/.gitkeep
A  src/__init__.py
A  src/data_wrappers.py
A  src/gen_synthetic.py
A  tests/.gitkeep
```

Note: this shell has `python3` but no `python` command. The module CLI and import smoke passed with `python3`; environments with `python` alias can use the exact `python -m ...` contract.
