# NBO Terraform

Учебная IaC-часть для сервиса скоринга NBO (Level 2).

Что описано:

- хранилище для batch-файлов скоринга (`nbo-batches`)
- контракт MLflow (tracking / artifacts) и alias `champion` / `challenger`
- манифест Airflow DAG: фактический `dag_id=nbo_retrain_pipeline`, файл `dags/nbo_retrain_dag.py`
- контракт API: `nbo-api`, `/health`, `/score`, `/batch-score`, `/metrics`
- контракт пайплайна: S3 key -> `feature_list.json` -> metric-gate -> ветвление

В этом контуре cloud не поднимается. `cloud.tf` - заглушка для будущего облачного деплоя: провайдер пока не выбран, ресурсы полностью закомментированы, `terraform init/validate/plan` не требуют cloud credentials.

## Проверка

```bash
cd infra
terraform fmt -check
terraform init
terraform validate
terraform plan -out=tfplan
terraform show -no-color tfplan > ../reports/terraform_plan.txt
terraform plan -destroy -out=tfdestroy
terraform show -no-color tfdestroy > ../reports/terraform_destroy_plan.txt
```

## Граница CI и оркестрации

CI - быстрый gate на PR: ставит зависимости, компилирует `src` / `dags`, гоняет smoke-тесты на синтетике, делает Terraform fmt/validate/plan. Обучение в CI не запускается.

Оркестрация - это Airflow DAG: sensor ждет батч, проверяет данные, считает фичи, обучает, оценивает, проходит metric-gate и промоутит либо пропускает alias модели. Это периодический runtime-процесс, он живет отдельно от pull request.

## Удаление

```bash
cd infra
terraform destroy
```

**Вывод:**

- инфраструктура не считается вечной
- storage / MLflow / Airflow / API / pipeline contract описаны декларативно
- перед apply/destroy надо смотреть plan
- `terraform.tfstate`, `tfplan`, `tfdestroy`, `.terraform/` и `.infra_artifacts/` не идут в git
