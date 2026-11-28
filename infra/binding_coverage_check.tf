resource "aws_cloudwatch_event_rule" "binding_coverage_check" {
  name                = "${var.project_name}-binding-coverage-check${local.name_suffix}"
  description         = "Daily check at 3 am Pacific: binding coverage and order reconciliation."
  schedule_expression = var.binding_coverage_check_schedule_expression

  # Only the rules are create-before-destroy. Terraform forces CBD onto
  # everything a CBD resource depends on. The rules depend on no resources,
  # but the targets and alarms depend on fixed-name Lambdas and queues, which
  # a create-first replacement would collide with ("already exists").
  lifecycle {
    create_before_destroy = true
  }
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
