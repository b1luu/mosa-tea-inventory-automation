resource "aws_sqs_queue" "webhook_jobs_dlq" {
  name                      = var.webhook_jobs_dlq_name
  message_retention_seconds = var.webhook_dlq_message_retention_seconds

  tags = local.common_tags
}

resource "aws_sqs_queue" "webhook_jobs" {
  name                       = var.webhook_jobs_queue_name
  visibility_timeout_seconds = var.webhook_queue_visibility_timeout_seconds
  message_retention_seconds  = var.webhook_queue_message_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.webhook_jobs_dlq.arn
    maxReceiveCount     = var.webhook_queue_max_receive_count
  })

  tags = local.common_tags
}
