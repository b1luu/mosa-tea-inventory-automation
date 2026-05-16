output "webhook_api_invoke_url" {
  description = "Base invoke URL for the webhook ingress HTTP API."
  value       = aws_apigatewayv2_stage.webhook.invoke_url
}

output "webhook_notification_url" {
  description = "Full Square webhook notification URL."
  value       = "${trimsuffix(aws_apigatewayv2_stage.webhook.invoke_url, "/")}/webhook/square"
}

output "manual_sync_api_invoke_url" {
  description = "Base invoke URL for the manual sync HTTP API."
  value       = aws_apigatewayv2_stage.manual_sync.invoke_url
}

output "manual_sync_url" {
  description = "Full Google Sheets batch manual sync URL."
  value       = "${trimsuffix(aws_apigatewayv2_stage.manual_sync.invoke_url, "/")}/admin/api/manual-count-sync-batch"
}

output "oauth_start_url" {
  description = "Full deployed OAuth start URL."
  value       = "${trimsuffix(aws_apigatewayv2_stage.oauth.invoke_url, "/")}/oauth/square/start"
}

output "oauth_callback_url" {
  description = "Full deployed OAuth callback URL."
  value       = "${trimsuffix(aws_apigatewayv2_stage.oauth.invoke_url, "/")}/oauth/square/callback"
}

output "webhook_jobs_queue_url" {
  description = "SQS queue URL for webhook jobs."
  value       = aws_sqs_queue.webhook_jobs.id
}

output "webhook_jobs_dlq_url" {
  description = "SQS dead-letter queue URL for webhook jobs."
  value       = aws_sqs_queue.webhook_jobs_dlq.id
}

output "lambda_function_names" {
  description = "Managed Lambda function names."
  value = {
    webhook_ingress        = aws_lambda_function.webhook_ingress.function_name
    webhook_worker         = aws_lambda_function.webhook_worker.function_name
    manual_sync            = aws_lambda_function.manual_count_sync.function_name
    oauth                  = aws_lambda_function.oauth.function_name
    binding_coverage_check = aws_lambda_function.binding_coverage_check.function_name
  }
}

output "dynamodb_table_names" {
  description = "Managed DynamoDB table names."
  value = {
    order_processing     = aws_dynamodb_table.order_processing.name
    webhook_events       = aws_dynamodb_table.webhook_events.name
    merchant_connections = aws_dynamodb_table.merchant_connections.name
    merchant_bindings    = aws_dynamodb_table.merchant_bindings.name
    oauth_state          = aws_dynamodb_table.oauth_state.name
  }
}

output "cloudwatch_alarm_names" {
  description = "Baseline CloudWatch alarm names for the webhook pipeline and coverage check."
  value = var.create_cloudwatch_alarms ? {
    webhook_jobs_dlq_visible_messages = aws_cloudwatch_metric_alarm.webhook_jobs_dlq_visible_messages[0].alarm_name
    webhook_jobs_oldest_message_age   = aws_cloudwatch_metric_alarm.webhook_jobs_oldest_message_age[0].alarm_name
    webhook_worker_errors             = aws_cloudwatch_metric_alarm.webhook_worker_errors[0].alarm_name
    binding_coverage_check_errors     = aws_cloudwatch_metric_alarm.binding_coverage_check_errors[0].alarm_name
  } : {}
}
