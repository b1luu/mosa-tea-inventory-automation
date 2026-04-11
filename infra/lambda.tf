resource "aws_cloudwatch_log_group" "webhook_ingress" {
  name              = "/aws/lambda/${var.webhook_ingress_lambda_function_name}"
  retention_in_days = var.log_retention_in_days
  tags              = local.common_tags

  lifecycle {
    ignore_changes = [
      retention_in_days,
      tags,
      tags_all,
    ]
  }
}

resource "aws_cloudwatch_log_group" "webhook_worker" {
  name              = "/aws/lambda/${var.worker_lambda_function_name}"
  retention_in_days = var.log_retention_in_days
  tags              = local.common_tags

  lifecycle {
    ignore_changes = [
      retention_in_days,
      tags,
      tags_all,
    ]
  }
}

resource "aws_cloudwatch_log_group" "manual_count_sync" {
  name              = "/aws/lambda/${var.manual_count_sync_lambda_function_name}"
  retention_in_days = var.log_retention_in_days
  tags              = local.common_tags

  lifecycle {
    ignore_changes = [
      retention_in_days,
      tags,
      tags_all,
    ]
  }
}

resource "aws_lambda_function" "webhook_ingress" {
  function_name = var.webhook_ingress_lambda_function_name
  role          = aws_iam_role.webhook_ingress.arn
  handler       = "app.lambda_webhook_ingress.lambda_handler"
  runtime       = var.lambda_runtime
  architectures = var.lambda_architectures
  memory_size   = var.lambda_memory_size_mb
  timeout       = var.lambda_timeout_seconds

  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)

  lifecycle {
    # The live Lambdas currently run python3.14, but the Terraform AWS provider
    # version used here validates only up to python3.13. Ignore runtime drift
    # during import/adoption until provider support catches up.
    ignore_changes = [
      runtime,
      filename,
      source_code_hash,
      publish,
      tags,
      tags_all,
      environment,
    ]
  }

  environment {
    variables = merge(
      local.common_store_env,
      {
        WEBHOOK_DISPATCH_MODE          = "sqs"
        WEBHOOK_JOB_QUEUE_URL          = aws_sqs_queue.webhook_jobs.id
        SQUARE_ACCESS_TOKEN            = var.square_access_token
        SQUARE_WEBHOOK_SIGNATURE_KEY   = var.square_webhook_signature_key
        SQUARE_WEBHOOK_NOTIFICATION_URL = "${aws_apigatewayv2_stage.webhook.invoke_url}/webhook/square"
      }
    )
  }

  tags = local.common_tags
}

resource "aws_lambda_function" "webhook_worker" {
  function_name = var.worker_lambda_function_name
  role          = aws_iam_role.webhook_worker.arn
  handler       = "app.lambda_sqs_worker.lambda_handler"
  runtime       = var.lambda_runtime
  architectures = var.lambda_architectures
  memory_size   = var.lambda_memory_size_mb
  timeout       = var.lambda_timeout_seconds

  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)

  lifecycle {
    ignore_changes = [
      runtime,
      filename,
      source_code_hash,
      publish,
      tags,
      tags_all,
      environment,
    ]
  }

  environment {
    variables = merge(
      local.common_store_env,
      {
        SQUARE_ACCESS_TOKEN = var.square_access_token
      }
    )
  }

  tags = local.common_tags
}

resource "aws_lambda_function" "manual_count_sync" {
  function_name = var.manual_count_sync_lambda_function_name
  role          = aws_iam_role.manual_count_sync.arn
  handler       = "app.lambda_manual_count_sync.lambda_handler"
  runtime       = var.lambda_runtime
  architectures = var.lambda_architectures
  memory_size   = var.lambda_memory_size_mb
  timeout       = var.lambda_timeout_seconds

  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)

  lifecycle {
    ignore_changes = [
      runtime,
      filename,
      source_code_hash,
      publish,
      tags,
      tags_all,
      environment,
    ]
  }

  environment {
    variables = {
      OPERATOR_API_TOKEN                 = var.operator_api_token
      MERCHANT_STORE_MODE                = "dynamodb"
      DYNAMODB_MERCHANT_CONNECTION_TABLE = aws_dynamodb_table.merchant_connections.name
      DYNAMODB_MERCHANT_CATALOG_BINDING_TABLE = aws_dynamodb_table.merchant_bindings.name
      MERCHANT_SECRET_PREFIX             = var.merchant_secret_prefix
      SQUARE_ENVIRONMENT                 = var.square_environment
    }
  }

  tags = local.common_tags
}

resource "aws_lambda_event_source_mapping" "webhook_worker_queue" {
  event_source_arn = aws_sqs_queue.webhook_jobs.arn
  function_name    = aws_lambda_function.webhook_worker.arn
  batch_size       = var.webhook_job_batch_size
  enabled          = true
  function_response_types = ["ReportBatchItemFailures"]

  lifecycle {
    ignore_changes = [
      metrics_config,
    ]
  }
}
