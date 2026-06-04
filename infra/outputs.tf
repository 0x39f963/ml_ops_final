output "storage_manifest_path" {
  value = local_file.storage_manifest.filename
}

output "mlflow_manifest_path" {
  value = local_file.mlflow_manifest.filename
}

output "airflow_manifest_path" {
  value = local_file.airflow_manifest.filename
}

output "api_manifest_path" {
  value = local_file.api_manifest.filename
}

output "pipeline_contract_manifest_path" {
  value = local_file.pipeline_contract_manifest.filename
}
