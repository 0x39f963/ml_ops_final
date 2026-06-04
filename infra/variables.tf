variable "environment" {
  type        = string
  description = "Environment name for NBO demo resources."
  default     = "dev"
}

variable "artifact_root" {
  type        = string
  description = "Local path for generated NBO infrastructure manifests."
  default     = "../.infra_artifacts"
}

variable "batch_bucket_name" {
  type        = string
  description = "Logical bucket name for quarterly NBO scoring batches."
  default     = "nbo-batches"
}

variable "mlflow_artifact_root" {
  type        = string
  description = "Local MLflow artifact store path for NBO model artifacts."
  default     = "../models"
}

variable "mlflow_tracking_uri" {
  type        = string
  description = "MLflow tracking URI used by local NBO services."
  default     = "file:../mlruns"
}

variable "enable_cloud" {
  type        = bool
  description = "Reserved P2 switch for cloud deploy; local plan ignores cloud resources."
  default     = false
}
