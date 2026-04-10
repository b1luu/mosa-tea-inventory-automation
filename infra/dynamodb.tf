resource "aws_dynamodb_table" "order_processing" {
  name         = var.order_processing_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "square_order_id"

  attribute {
    name = "square_order_id"
    type = "S"
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "webhook_events" {
  name         = var.webhook_event_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "event_id"

  attribute {
    name = "event_id"
    type = "S"
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "merchant_connections" {
  name         = var.merchant_connection_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "environment_merchant_id"

  attribute {
    name = "environment_merchant_id"
    type = "S"
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "merchant_bindings" {
  name         = var.merchant_binding_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "environment_merchant_location_id"
  range_key    = "version"

  attribute {
    name = "environment_merchant_location_id"
    type = "S"
  }

  attribute {
    name = "version"
    type = "N"
  }

  tags = local.common_tags
}
