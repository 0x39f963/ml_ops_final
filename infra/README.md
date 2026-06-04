# NBO Terraform

Учебная IaC-часть для Level 2 NBO scoring service.

Что описано:

- storage для scoring-batch файлов (`nbo-batches`)
- MLflow tracking/artifact contract и alias `champion` / `challenger`
- Airflow DAG manifest: фактический `dag_id=nbo_retrain_pipeline`, файл `dags/nbo_retrain_dag.py`
- API contract: `nbo-api`, `/health`, `/score`, `/batch-score`, `/metrics`
- pipeline contract: S3 key -> `feature_list.json` -> metric gate -> branch join

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

## CI vs orchestration boundary

CI - быстрый PR gate: install deps, compile `src` / `dags`, smoke tests on synthetic, Terraform fmt/validate/plan. Training must NOT run in CI.

Orchestration - Airflow DAG: sensor waits for a batch, validates data, builds features, trains, evaluates, applies metric gate, and promotes or skips model alias. Это периодический runtime-процесс, не job pull request.

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
