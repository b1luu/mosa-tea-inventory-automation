locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment_name
    ManagedBy   = "terraform"
    Repository  = "b1luu/mosa-tea-inventory-automation"
  }

  merchant_store_env = {
    MERCHANT_STORE_MODE                     = "dynamodb"
    DYNAMODB_MERCHANT_CONNECTION_TABLE      = aws_dynamodb_table.merchant_connections.name
    DYNAMODB_MERCHANT_CATALOG_BINDING_TABLE = aws_dynamodb_table.merchant_bindings.name
    MERCHANT_SECRET_PREFIX                  = var.merchant_secret_prefix
    SQUARE_ENVIRONMENT                      = var.square_environment
  }

  common_store_env = merge(
    local.merchant_store_env,
    {
      ORDER_PROCESSING_STORE_MODE     = "dynamodb"
      WEBHOOK_EVENT_STORE_MODE        = "dynamodb"
      DYNAMODB_ORDER_PROCESSING_TABLE = aws_dynamodb_table.order_processing.name
      DYNAMODB_WEBHOOK_EVENT_TABLE    = aws_dynamodb_table.webhook_events.name
    }
  )

  oauth_state_env = {
    OAUTH_STATE_STORE_MODE      = "dynamodb"
    DYNAMODB_OAUTH_STATE_TABLE  = aws_dynamodb_table.oauth_state.name
    OAUTH_STATE_MAX_AGE_SECONDS = tostring(var.oauth_state_max_age_seconds)
  }
}
