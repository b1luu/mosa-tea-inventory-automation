resource "aws_cloudwatch_event_rule" "binding_coverage_check" {
  name                = "${var.project_name}-binding-coverage-check"
  description         = "Run the binding coverage check once per day."
  schedule_expression = var.binding_coverage_check_schedule_expression
}

resource "aws_cloudwatch_event_target" "binding_coverage_check" {
  rule      = aws_cloudwatch_event_rule.binding_coverage_check.name
  target_id = "binding-coverage-check"
  arn       = aws_lambda_function.binding_coverage_check.arn
}

resource "aws_lambda_permission" "allow_binding_coverage_check_schedule" {
  statement_id  = "AllowBindingCoverageCheckScheduleInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.binding_coverage_check.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.binding_coverage_check.arn
}
