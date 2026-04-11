# Terraform Infrastructure

This repo now includes a public-safe Terraform scaffold under [`infra/`](../infra) for the current AWS shape:

- webhook ingress Lambda
- webhook worker Lambda
- manual count sync Lambda
- webhook HTTP API
- manual sync HTTP API
- SQS main queue + DLQ
- DynamoDB tables
- Lambda execution roles and runtime policies

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
- It parameterizes sensitive values but does not store them.
- It models the merchant bindings table with a partition key plus `version` sort key, which matches the current DynamoDB code path.
