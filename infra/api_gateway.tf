resource "aws_apigatewayv2_api" "webhook" {
  name          = var.webhook_api_name
  protocol_type = "HTTP"
  tags          = local.common_tags

  lifecycle {
    ignore_changes = [
      tags,
      tags_all,
    ]
  }
}

resource "aws_apigatewayv2_api" "manual_sync" {
  name          = var.manual_sync_api_name
  protocol_type = "HTTP"
  tags          = local.common_tags

  lifecycle {
    ignore_changes = [
      tags,
      tags_all,
    ]
  }
}

resource "aws_apigatewayv2_integration" "webhook_ingress" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.webhook_ingress.arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "manual_count_sync" {
  api_id                 = aws_apigatewayv2_api.manual_sync.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.manual_count_sync.arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "webhook_ingress" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook/square"
  target    = "integrations/${aws_apigatewayv2_integration.webhook_ingress.id}"
}

resource "aws_apigatewayv2_route" "manual_count_sync" {
  api_id    = aws_apigatewayv2_api.manual_sync.id
  route_key = "POST /admin/api/manual-count-sync-batch"
  target    = "integrations/${aws_apigatewayv2_integration.manual_count_sync.id}"
}

resource "aws_apigatewayv2_stage" "webhook" {
  api_id      = aws_apigatewayv2_api.webhook.id
  name        = var.webhook_api_stage_name
  auto_deploy = true
  tags        = local.common_tags

  lifecycle {
    ignore_changes = [
      tags,
      tags_all,
    ]
  }
}

resource "aws_apigatewayv2_stage" "manual_sync" {
  api_id      = aws_apigatewayv2_api.manual_sync.id
  name        = var.manual_sync_api_stage_name
  auto_deploy = true
  tags        = local.common_tags

  lifecycle {
    ignore_changes = [
      tags,
      tags_all,
    ]
  }
}

resource "aws_lambda_permission" "allow_webhook_api_invoke" {
  count         = var.manage_lambda_permissions ? 1 : 0
  statement_id  = "AllowWebhookApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook_ingress.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*/webhook/square"
}

resource "aws_lambda_permission" "allow_manual_sync_api_invoke" {
  count         = var.manage_lambda_permissions ? 1 : 0
  statement_id  = "AllowManualSyncApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.manual_count_sync.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.manual_sync.execution_arn}/*/*/admin/api/manual-count-sync-batch"
}
