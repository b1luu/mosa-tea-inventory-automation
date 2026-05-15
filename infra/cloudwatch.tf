resource "aws_cloudwatch_metric_alarm" "webhook_jobs_dlq_visible_messages" {
  count = var.create_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.project_name}-webhook-jobs-dlq-visible-messages"
  alarm_description   = "The webhook DLQ should normally stay empty. Investigate poison jobs before replaying them."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = var.webhook_dlq_visible_messages_alarm_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    QueueName = aws_sqs_queue.webhook_jobs_dlq.name
  }
  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
  tags          = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "webhook_jobs_oldest_message_age" {
  count = var.create_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.project_name}-webhook-jobs-oldest-message-age"
  alarm_description   = "The webhook worker should keep the main queue draining. A stale oldest message means the pipeline is stuck or underprovisioned."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = var.webhook_jobs_oldest_message_age_alarm_threshold_seconds
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    QueueName = aws_sqs_queue.webhook_jobs.name
  }
  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
  tags          = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "webhook_worker_errors" {
  count = var.create_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${var.project_name}-webhook-worker-errors"
  alarm_description   = "The webhook worker should not be raising Lambda errors during normal processing."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.webhook_worker_errors_alarm_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.webhook_worker.function_name
  }
  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
  tags          = local.common_tags
}
