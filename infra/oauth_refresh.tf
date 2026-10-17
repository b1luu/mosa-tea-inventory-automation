# Proactive OAuth token refresh. The worker also refreshes on demand when a
# token is within five minutes of expiry; this schedule renews ten days ahead
# so a failure alarms while there is still time to reconnect.
resource "aws_cloudwatch_event_rule" "oauth_refresh" {
  name                = "${var.project_name}-oauth-refresh"
  description         = "Refresh Square OAuth tokens that expire within ten days."
  schedule_expression = var.oauth_refresh_schedule_expression
}

resource "aws_cloudwatch_event_target" "oauth_refresh" {
  rule      = aws_cloudwatch_event_rule.oauth_refresh.name
  target_id = "oauth-refresh"
  arn       = aws_lambda_function.oauth_refresh.arn
}

resource "aws_lambda_permission" "allow_oauth_refresh_schedule" {
  statement_id  = "AllowOAuthRefreshScheduleInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.oauth_refresh.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.oauth_refresh.arn
}
