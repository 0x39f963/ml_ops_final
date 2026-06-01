# Generated at: 2026-06-01 13:41:00 MSK

locals {
  base_path = "${var.artifact_root}/${var.environment}"
}

resource "local_file" "storage_manifest" {
  filename = "${local.base_path}/storage_manifest.txt"
  content  = "bucket=${var.batch_bucket_name}\npath=incoming/YYYY-MM-DD/scoring_batch.parquet\n"
}

resource "local_file" "mlflow_manifest" {
  filename = "${local.base_path}/mlflow_manifest.txt"
  content  = "tracking_uri=${var.mlflow_tracking_uri}\nartifact_store=${var.mlflow_artifact_root}\naliases=champion,challenger\n"
}

resource "local_file" "airflow_manifest" {
  filename = "${local.base_path}/airflow_manifest.txt"
  content  = "dag_id=nbo_retrain_pipeline\ndag_file=dags/nbo_retrain_dag.py\nsensor=S3KeySensor_or_local_FileSensor\nsensor_mode_env=NBO_USE_S3_SENSOR\n"
}

resource "local_file" "api_manifest" {
  filename = "${local.base_path}/api_manifest.txt"
  content  = "service=nbo-api\nhealth=/health\nscore=/score\nbatch_score=/batch-score\nmetrics=/metrics\n"
}

resource "local_file" "pipeline_contract_manifest" {
  filename = "${local.base_path}/pipeline_contract_manifest.txt"
  content  = <<-EOT
    s3_bucket=${var.batch_bucket_name}
    s3_key_template=incoming/{{ ds }}/scoring_batch.parquet
    feature_list_source=artifacts/feature_list.json
    gate=precision@10_new>=precision@10_champion
    branch_join_trigger_rule=none_failed_min_one_success
  EOT
}
