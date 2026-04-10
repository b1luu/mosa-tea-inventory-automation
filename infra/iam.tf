data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "webhook_ingress" {
  name               = coalesce(var.webhook_ingress_lambda_role_name, "${var.webhook_ingress_lambda_function_name}-role")
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

resource "aws_iam_role" "webhook_worker" {
  name               = coalesce(var.worker_lambda_role_name, "${var.worker_lambda_function_name}-role")
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

resource "aws_iam_role" "manual_count_sync" {
  name               = coalesce(var.manual_count_sync_lambda_role_name, "${var.manual_count_sync_lambda_function_name}-role")
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy_attachment" "webhook_ingress_basic_execution" {
  role       = aws_iam_role.webhook_ingress.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "webhook_worker_basic_execution" {
  role       = aws_iam_role.webhook_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "manual_count_sync_basic_execution" {
  role       = aws_iam_role.manual_count_sync.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "webhook_ingress_runtime" {
  statement {
    sid    = "WebhookQueueDispatch"
    effect = "Allow"
    actions = [
      "sqs:SendMessage",
      "sqs:GetQueueAttributes"
    ]
    resources = [aws_sqs_queue.webhook_jobs.arn]
  }

  statement {
    sid    = "WebhookStateTables"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:DescribeTable"
    ]
    resources = [
      aws_dynamodb_table.order_processing.arn,
      aws_dynamodb_table.webhook_events.arn,
      aws_dynamodb_table.merchant_connections.arn,
    ]
  }

  statement {
    sid    = "MerchantBindingRead"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:DescribeTable"
    ]
    resources = [aws_dynamodb_table.merchant_bindings.arn]
  }

  statement {
    sid    = "MerchantSecretsLifecycle"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
      "secretsmanager:PutSecretValue",
      "secretsmanager:CreateSecret",
      "secretsmanager:DeleteSecret"
    ]
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.merchant_secret_prefix}*"
    ]
  }
}

resource "aws_iam_role_policy" "webhook_ingress_runtime" {
  name   = "webhook-ingress-runtime-access"
  role   = aws_iam_role.webhook_ingress.id
  policy = data.aws_iam_policy_document.webhook_ingress_runtime.json
}

data "aws_iam_policy_document" "webhook_worker_runtime" {
  statement {
    sid    = "WebhookQueueConsume"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes"
    ]
    resources = [aws_sqs_queue.webhook_jobs.arn]
  }

  statement {
    sid    = "WebhookStateTables"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:DescribeTable"
    ]
    resources = [
      aws_dynamodb_table.order_processing.arn,
      aws_dynamodb_table.webhook_events.arn,
      aws_dynamodb_table.merchant_connections.arn,
      aws_dynamodb_table.merchant_bindings.arn,
    ]
  }

  statement {
    sid    = "MerchantSecretsRead"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret"
    ]
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.merchant_secret_prefix}*"
    ]
  }
}

resource "aws_iam_role_policy" "webhook_worker_runtime" {
  name   = "webhook-worker-runtime-access"
  role   = aws_iam_role.webhook_worker.id
  policy = data.aws_iam_policy_document.webhook_worker_runtime.json
}

data "aws_iam_policy_document" "manual_count_sync_runtime" {
  statement {
    sid    = "MerchantTableRead"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:DescribeTable"
    ]
    resources = [
      aws_dynamodb_table.merchant_connections.arn,
      aws_dynamodb_table.merchant_bindings.arn,
    ]
  }

  statement {
    sid    = "MerchantSecretsRead"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret"
    ]
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.merchant_secret_prefix}*"
    ]
  }
}

resource "aws_iam_role_policy" "manual_count_sync_runtime" {
  name   = "manual-count-sync-runtime-access"
  role   = aws_iam_role.manual_count_sync.id
  policy = data.aws_iam_policy_document.manual_count_sync_runtime.json
}
