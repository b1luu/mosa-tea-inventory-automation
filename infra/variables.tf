variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-west-2"
}

variable "project_name" {
  description = "Project prefix used for naming and tagging."
  type        = string
  default     = "mosa-tea"
}

variable "environment_name" {
  description = "Logical environment label used in tags."
  type        = string
  default     = "sandbox"
}

variable "lambda_package_path" {
  description = "Path to the shared Lambda deployment zip. Build it before apply."
  type        = string
  default     = "../.build/lambda-package.zip"
}

variable "lambda_runtime" {
  description = "Managed runtime for all Python Lambdas. Keep this at python3.13 until the Terraform AWS provider supports python3.14."
  type        = string
  default     = "python3.13"
}

variable "lambda_architectures" {
  description = "Lambda CPU architecture."
  type        = list(string)
  default     = ["x86_64"]
}

variable "lambda_memory_size_mb" {
  description = "Default memory size for project Lambdas."
  type        = number
  default     = 512
}

variable "lambda_timeout_seconds" {
  description = "Default timeout for project Lambdas."
  type        = number
  default     = 30
}

variable "log_retention_in_days" {
  description = "CloudWatch log retention for managed Lambda log groups."
  type        = number
  default     = 14
}

variable "webhook_api_name" {
  description = "HTTP API name for Square webhook ingress."
  type        = string
  default     = "mosa-tea-webhook-api"
}

variable "manual_sync_api_name" {
  description = "HTTP API name for Google Sheets manual sync."
  type        = string
  default     = "mosa-tea-manual-sync-api"
}

variable "webhook_api_stage_name" {
  description = "Stage name for the webhook HTTP API."
  type        = string
  default     = "$default"
}

variable "manual_sync_api_stage_name" {
  description = "Stage name for the manual sync HTTP API."
  type        = string
  default     = "$default"
}

variable "worker_lambda_function_name" {
  description = "Lambda function name for the webhook worker."
  type        = string
  default     = "mosa-tea-webhook-worker"
}

variable "webhook_ingress_lambda_function_name" {
  description = "Lambda function name for webhook ingress."
  type        = string
  default     = "mosa-tea-webhook-ingress"
}

variable "manual_count_sync_lambda_function_name" {
  description = "Lambda function name for Google Sheets batch manual sync."
  type        = string
  default     = "mosa-tea-manual-count-sync"
}

variable "webhook_ingress_lambda_role_name" {
  description = "IAM role name for the webhook ingress Lambda. Set this to the existing live role name when importing resources."
  type        = string
  default     = null
}

variable "worker_lambda_role_name" {
  description = "IAM role name for the webhook worker Lambda. Set this to the existing live role name when importing resources."
  type        = string
  default     = null
}

variable "manual_count_sync_lambda_role_name" {
  description = "IAM role name for the manual count sync Lambda. Set this to the existing live role name when importing resources."
  type        = string
  default     = null
}

variable "webhook_jobs_queue_name" {
  description = "Main SQS queue name for webhook jobs."
  type        = string
  default     = "mosa-tea-webhook-jobs"
}

variable "webhook_jobs_dlq_name" {
  description = "Dead-letter queue name for webhook jobs."
  type        = string
  default     = "mosa-tea-webhook-jobs-dlq"
}

variable "webhook_queue_visibility_timeout_seconds" {
  description = "Visibility timeout for the main webhook jobs queue."
  type        = number
  default     = 120
}

variable "webhook_queue_message_retention_seconds" {
  description = "Message retention for the main webhook jobs queue."
  type        = number
  default     = 345600
}

variable "webhook_dlq_message_retention_seconds" {
  description = "Message retention for the webhook DLQ."
  type        = number
  default     = 1209600
}

variable "webhook_queue_max_receive_count" {
  description = "Number of failed receives before SQS redrives to the DLQ."
  type        = number
  default     = 3
}

variable "webhook_job_batch_size" {
  description = "Lambda batch size for the webhook worker event source mapping."
  type        = number
  default     = 1
}

variable "order_processing_table_name" {
  description = "DynamoDB table for order processing state."
  type        = string
  default     = "mosa-tea-order-processing"
}

variable "webhook_event_table_name" {
  description = "DynamoDB table for webhook event ledger state."
  type        = string
  default     = "mosa-tea-webhook-events"
}

variable "merchant_connection_table_name" {
  description = "DynamoDB table for merchant connection metadata."
  type        = string
  default     = "mosa-tea-merchant-connections"
}

variable "merchant_binding_table_name" {
  description = "DynamoDB table for approved merchant catalog bindings."
  type        = string
  default     = "mosa-tea-merchant-bindings"
}

variable "merchant_secret_prefix" {
  description = "Secrets Manager prefix for merchant auth secrets."
  type        = string
  default     = "mosa-tea/merchant-auth"
}

variable "square_environment" {
  description = "Square environment name passed to the Lambdas."
  type        = string
  default     = "sandbox"
}

variable "square_access_token" {
  description = "Square access token used by the webhook ingress and worker Lambdas."
  type        = string
  sensitive   = true
}

variable "square_webhook_signature_key" {
  description = "Square webhook signature key for ingress validation."
  type        = string
  sensitive   = true
}

variable "operator_api_token" {
  description = "Operator token used by the manual count sync Lambda and Google Sheets."
  type        = string
  sensitive   = true
}
