# b01 - проверка каркаса

это лог по первой версии каркаса b01. свежие проверки по пунктам f1-f4 и стаб на 40000 строк - в [b01_followup_f1_f4_verification_log.md](b01_followup_f1_f4_verification_log.md).

## генерация синтетики

команда:

```bash
make data
```

вывод:

```text
python3 -m src.gen_synthetic --rows 5000 --out data/sample_synth.parquet
path=data/sample_synth.parquet
rows=5000
unique_client_id=2750
fam_box_share=0.8500
inn_is_pseudo_share=0.2200
```

## смоук генератора на 100 строк

команда:

```bash
python3 -m src.gen_synthetic --rows 100 --out /tmp/_smoke.parquet
```

вывод:

```text
path=/tmp/_smoke.parquet
rows=100
unique_client_id=55
fam_box_share=0.8500
inn_is_pseudo_share=0.2200
```

## импорт обертки данных

команда:

```bash
python3 -c "import src.data_wrappers; print('ok')"
```

вывод:

```text
ok
```

## проверка схемы сэмпла

команда:

```bash
python3 -c "import pandas as pd; df=pd.read_parquet('data/sample_synth.parquet'); print(df.shape); print(sorted(df.columns)); print((df.product_family=='FAM_BOX').mean()); print(df.inn_is_pseudo.mean())"
```

вывод:

```text
(5000, 10)
['client_id', 'inn_is_pseudo', 'lifecycle_role', 'product', 'product_family', 'quarter', 'revenue_proxy', 'segment', 'ts', 'year']
0.85
0.22
```

## смоук cutoff в обертке

команда:

```bash
python3 -c "from src.data_wrappers import load_events, normalize_client_id; df=load_events('2020-12-31'); print(df.shape); print(normalize_client_id(' C 123 '))"
```

вывод:

```text
(1190, 10)
C123
```

## компиляция

команда:

```bash
python3 -m compileall -q src
```

вывод пустой, ошибок компиляции нет.

## размер сэмпла

команда:

```bash
du -h data/sample_synth.parquet
```

вывод:

```text
112K	data/sample_synth.parquet
```

## leak-check

команда:

```bash
make leak-check
```

вывод:

```text
checking gitignore gates
checking tracked and staged file list
leak-check passed
```

код возврата 0.

## тесты

команда:

```bash
make test
```

вывод:

```text
no tests yet
```

тестов на этом шаге еще нет, добавляю их в следующих ветках.

## git status

команда:

```bash
git status --short
```

вывод:

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

примечание: в этом окружении есть python3, но нет алиаса python. cli модулей и импорт-смоук прошли на python3; там где алиас python настроен, контракт python -m ... работает так же.
