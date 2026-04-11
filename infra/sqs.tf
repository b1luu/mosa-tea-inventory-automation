resource "aws_sqs_queue" "webhook_jobs_dlq" {
  name                      = var.webhook_jobs_dlq_name
  max_message_size          = var.sqs_max_message_size
  message_retention_seconds = var.webhook_dlq_message_retention_seconds
  receive_wait_time_seconds = var.webhook_dlq_receive_wait_time_seconds

  tags = local.common_tags

  lifecycle {
    ignore_changes = [
      max_message_size,
      receive_wait_time_seconds,
      tags,
      tags_all,
      visibility_timeout_seconds,
    ]
  }
}

resource "aws_sqs_queue" "webhook_jobs" {
  name                       = var.webhook_jobs_queue_name
  max_message_size           = var.sqs_max_message_size
  visibility_timeout_seconds = var.webhook_queue_visibility_timeout_seconds
  message_retention_seconds  = var.webhook_queue_message_retention_seconds
  receive_wait_time_seconds  = var.webhook_queue_receive_wait_time_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.webhook_jobs_dlq.arn
    maxReceiveCount     = var.webhook_queue_max_receive_count
  })

  tags = local.common_tags

  lifecycle {
    ignore_changes = [
      max_message_size,
      receive_wait_time_seconds,
      tags,
      tags_all,
      visibility_timeout_seconds,
    ]
  }
}
