# Terraform Infrastructure

This repo now includes a public-safe Terraform scaffold under [`infra/`](../infra) for the current AWS shape:

- webhook ingress Lambda
- webhook worker Lambda
- manual count sync Lambda
- OAuth Lambda
- webhook HTTP API
- manual sync HTTP API
- OAuth HTTP API
- SQS main queue + DLQ
- CloudWatch baseline alarms
- DynamoDB tables
- Lambda execution roles and runtime policies

The current Terraform scope is a mix of:

- imported live infrastructure that already existed in AWS
- new OAuth infrastructure being added on top of that live stack

## Baseline Alarms

The Terraform scaffold now includes a minimal CloudWatch alarm set for the webhook pipeline:

- visible messages in the webhook DLQ
- oldest visible message age on the main webhook jobs queue
- webhook worker Lambda errors

Default thresholds:

- DLQ visible messages: `1`
- oldest visible main-queue message age: `300` seconds
- webhook worker Lambda errors: `1` over `5` minutes

These alarms are intentionally infrastructure-level only. They do not require any application refactor or custom metrics.

If you want notifications, set:

- `alarm_notification_topic_arn`

to an existing SNS topic ARN in your local ignored `terraform.tfvars`.

If you need to suppress alarms during an import-first adoption step, set:

- `create_cloudwatch_alarms = false`

## Public-Safe Design

The Terraform files are safe to keep in a public repository because they define infrastructure shape, not secret values.

Safe to keep in git:

- resource names
- route paths
- table schemas
- IAM policy structure
- environment variable keys
- queue wiring
- timeout and memory settings
- OAuth callback URL shape
- baseline alarm thresholds and optional SNS wiring

Do not commit:

- filled-in `terraform.tfvars`
- Square access tokens
- operator token values
- webhook signature keys

Use:

- local ignored `*.tfvars`
- CI/CD secret injection
- Terraform Cloud variables

## Current Scope

Files:

- [`infra/versions.tf`](../infra/versions.tf)
- [`infra/variables.tf`](../infra/variables.tf)
- [`infra/dynamodb.tf`](../infra/dynamodb.tf)
- [`infra/sqs.tf`](../infra/sqs.tf)
- [`infra/cloudwatch.tf`](../infra/cloudwatch.tf)
- [`infra/iam.tf`](../infra/iam.tf)
- [`infra/lambda.tf`](../infra/lambda.tf)
- [`infra/api_gateway.tf`](../infra/api_gateway.tf)
- [`infra/outputs.tf`](../infra/outputs.tf)
- [`infra/terraform.tfvars.example`](../infra/terraform.tfvars.example)

## Adopt Existing AWS Resources

This project already has live AWS resources, so the first safe adoption path is:

1. create a local `infra/terraform.tfvars` from the example
2. set the existing Lambda IAM role names in `terraform.tfvars`
3. run `terraform init`
4. import existing resources into state
5. run `terraform plan`
6. reconcile drift before applying any changes

This avoids Terraform trying to recreate resources that already exist.

That adoption guidance applies to the pre-existing stack:

- webhook ingress Lambda
- webhook worker Lambda
- manual count sync Lambda
- webhook API
- manual sync API
- SQS queues
- merchant/order/webhook DynamoDB tables
- existing Lambda roles

The OAuth API/Lambda/state-table slice is different:

- it is a new extension to the live stack
- it is expected to be created by Terraform
- it is not imported from an already-existing deployed OAuth stack

## Basic Workflow

Build the shared Lambda zip first:

```bash
mkdir -p .build/package/data
./.venv/bin/pip install -r requirements.txt --target .build/package
cp -R app .build/package/app
cp data/inventory_item_map.json data/recipe_map.json .build/package/data/
find .build/package -type d -name "__pycache__" -prune -exec rm -rf {} +
find .build/package -type f -name "*.pyc" -delete
(cd .build/package && zip -r ../lambda-package.zip .)
```

Then from `infra/`:

```bash
terraform init
terraform plan -var-file=terraform.tfvars
```

When adopting the current live stack, make sure these variables match the IAM role names AWS already assigned to the Lambdas:

- `webhook_ingress_lambda_role_name`
- `worker_lambda_role_name`
- `manual_count_sync_lambda_role_name`

Without that, Terraform will assume it should create replacement roles with clean names, which is not what you want for a safe import-first rollout.

For the new OAuth slice, Terraform also expects:

- `square_oauth_client_id`
- `square_oauth_client_secret`
- `square_oauth_redirect_uri`

Those are required for the deployed callback flow and should be supplied through your local ignored `terraform.tfvars`.

## OAuth Bootstrap Sequence

Because the dedicated OAuth API is a new resource, the final deployed callback URL does not exist until after the first Terraform apply.

That means OAuth setup is a two-step bootstrap:

1. Put the Square sandbox application credentials into local `terraform.tfvars`.
2. Use a temporary `square_oauth_redirect_uri` value for the first apply.
3. Run `terraform apply` to create the OAuth API, OAuth Lambda, and OAuth state table.
4. Read the generated `oauth_callback_url` Terraform output.
5. Update both:
   - the Square Sandbox Redirect URL in the Square Developer Dashboard
   - `square_oauth_redirect_uri` in local `terraform.tfvars`
6. Run `terraform apply` again so the deployed Lambda config and Square app configuration match exactly.

Until that second apply is complete, the deployed OAuth callback should be treated as not fully wired.

## Runtime Compatibility Note

The current live Lambdas run `python3.14`, but the Terraform AWS provider version used by this scaffold currently validates Lambda runtimes only through `python3.13`.

To keep planning and import safe:

- the scaffold defaults `lambda_runtime` to `python3.13`
- the Lambda resources ignore runtime drift during adoption

This is a temporary compatibility shim for Terraform planning. Once the provider supports `python3.14`, you can remove the workaround and align the runtime in Terraform with the live AWS setting.

## IAM Adoption Mode

The current live Lambda execution roles were created outside Terraform and already have attached/inline policies. To avoid Terraform trying to replace or rewire those roles during the first import:

- the scaffold defaults `lambda_role_path` to `/service-role/`
- the role resources ignore drift for existing attached and inline policies
- `manage_lambda_role_policies` defaults to `false`
- `manage_lambda_permissions` defaults to `false`

That means the first Terraform adoption phase focuses on importing the existing roles safely. After the imported state is stable, you can decide whether to model the role policies explicitly and turn policy management on later.

## Tag And Queue Drift During Adoption

The live stack already has some hand-applied tags and queue settings. To keep the first adoption plan safe:

- `manage_resource_tags` defaults to `false`
- SQS defaults are aligned with the current live queues
- the merchant bindings table is modeled as a hash-only table, matching the live schema

That reduces noisy drift and avoids dangerous replacement of the bindings table during import.

## Notes

- The Terraform scaffold uses a shared Lambda package, matching the current GitHub Actions deploy model.
- Terraform ignores Lambda package/hash drift for all four functions, so infra-only applies do not accidentally redeploy code when the local build artifact differs from what is live in AWS.
- It parameterizes sensitive values but does not store them.
- It now includes a dedicated OAuth state table with TTL for short-lived callback state.
- The OAuth API is intentionally separate from the webhook API and manual sync API to keep automation ingress, reconciliation tooling, and auth/onboarding concerns modular.
