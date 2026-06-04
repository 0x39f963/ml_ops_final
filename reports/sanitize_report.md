# Отчет по анти-лику (sanitize)

## что проверяли

- просканировано публичное дерево `ml005/`
- из проверки исключены runtime / gitignored каталоги: `.git`, `.venv`, `mlruns`, `models`, `data`
- бинарные файлы исключены из текстового поиска: картинки / parquet / csv / html / pyc
- реальные внутренние имена в этот отчет не копируются

## проверки

| категория | шаблон команды | результат |
|---|---|---|
| шаблон названия компании | `rg -n -i <company-name-pattern> ml005 ...` | пусто |
| маркер реального сырого продукта | `rg -n -i <raw-product-marker> ml005 ...` | пусто |
| отдельный 10/12-значный id | `rg -n '(^|[^A-Za-z0-9_.])[0-9]{10}...` по md/py/ipynb | пусто |
| слова, похожие на секреты | `rg -n -i <credential-like-pattern> ml005 ...` | проверено, реальных секретов нет |
| masking-линт (е с точками / длинное тире) | `grep -rnP '[\\x{0451}\\x{0401}\\x{2014}]' ml005 --include='*.md' --include='*.ipynb' ...` | пусто |
| git anti-leak статус | `git -C ml005 status --porcelain | grep -E '\\.pkl$|\\.joblib$|\\.parquet$|mlruns|\\.env$'` | пусто |
| gitignore-гейт | `git -C ml005 check-ignore -v data/real.parquet ... .env` | все нужные local-only пути под игнором |

## просмотренные неопасные совпадения

- демо-креды compose / Airflow: `admin/admin`, `minioadmin/minioadmin` - допустимы для локального демо-стека
- placeholder env-ключи Grafana / MinIO - только демо-дефолты, реальные значения остаются в `.env`
- хэширование использует локальную seed-строку - это детерминированный вход хэша, не секрет
- в ci-доках упоминается только политика по секретам, без самих значений

## доказательство gitignore

```text
.gitignore:7:data/**/*.parquet data/real.parquet
.gitignore:8:data/feature_store/ data/feature_store/q=2022Q1/part.parquet
.gitignore:17:*.pkl models/model.pkl
.gitignore:18:*.joblib models/model.joblib
.gitignore:19:mlruns/ mlruns/0/meta.yaml
.gitignore:25:.env .env
.gitignore:29:*/__pycache__/ src/__pycache__/x.pyc
```

## примечания

- `data/sample_synth.parquet` синтетический и разрешен в `.gitignore`.
- большие csv с замерами latency синтетические, но игнорируются: они большие и пересоздаются ноутбуком.
- визуальные доказательства - в `screenshots/`, каталог - `screenshots/INDEX.md`; ни один скрин не выдуман.

**Вывод:** чисто. Не найдено ни шаблона названия компании, ни отдельных id-номеров, ни реальных сырых имен продуктов, ни реальных секретов; masking-линт пуст; локальные пути данных / модели / env / mlruns под gitignore.
