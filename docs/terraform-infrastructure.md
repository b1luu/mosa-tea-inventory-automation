# Terraform Infrastructure

This repo now includes a public-safe Terraform scaffold under [`infra/`](../infra) for the current AWS shape:

- webhook ingress Lambda
- webhook worker Lambda
- manual count sync Lambda
- OAuth Lambda
- scheduled binding coverage check Lambda
- scheduled OAuth refresh Lambda
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
- scheduled binding coverage check Lambda errors
- scheduled OAuth refresh Lambda errors

Default thresholds:

- DLQ visible messages: `1`
- oldest visible main-queue message age: `1200` seconds (paid-but-open orders are queued with a 900-second hold, so this must exceed 900)
- webhook worker Lambda errors: `1` over `5` minutes
- binding coverage check Lambda errors: `1` over `5` minutes
- OAuth refresh Lambda errors: `1` over `5` minutes

These alarms are intentionally infrastructure-level only. They do not require any application refactor or custom metrics.

If you want notifications, set:

- `alarm_notification_topic_arn`

to an existing SNS topic ARN in your local ignored `sandbox.tfvars`.

The same SNS topic is also reused by the scheduled binding coverage check when it finds:

- blocking binding issues
- unmapped live sold variations
- merchant-level evaluation failures such as missing selected locations or token-refresh/report errors

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

- filled-in `sandbox.tfvars`
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
- [`infra/locals.tf`](../infra/locals.tf)
- [`infra/dynamodb.tf`](../infra/dynamodb.tf)
- [`infra/sqs.tf`](../infra/sqs.tf)
- [`infra/cloudwatch.tf`](../infra/cloudwatch.tf)
- [`infra/iam.tf`](../infra/iam.tf)
- [`infra/lambda.tf`](../infra/lambda.tf)
- [`infra/binding_coverage_check.tf`](../infra/binding_coverage_check.tf)
- [`infra/oauth_refresh.tf`](../infra/oauth_refresh.tf)
- [`infra/api_gateway.tf`](../infra/api_gateway.tf)
- [`infra/outputs.tf`](../infra/outputs.tf)
- [`infra/sandbox.tfvars.example`](../infra/sandbox.tfvars.example)
- [`infra/production.tfvars.example`](../infra/production.tfvars.example)

## Adopt Existing AWS Resources

This project already has live AWS resources, so the first safe adoption path is:

1. create a local `infra/sandbox.tfvars` from the example
2. set the existing Lambda IAM role names in `sandbox.tfvars`
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

Build the Lambda zips first:

```bash
rm -rf .build/runtime314 .build/runtime313

build_package () {
  PACKAGE_ROOT="$1"
  PY_VERSION="$2"

  mkdir -p "${PACKAGE_ROOT}/package/data"
  ./.venv/bin/pip install \
    --requirement requirements.txt \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version "${PY_VERSION}" \
    --only-binary=:all: \
    --target "${PACKAGE_ROOT}/package"
  cp -R app "${PACKAGE_ROOT}/package/app"
  cp data/inventory_item_map.json data/recipe_map.json "${PACKAGE_ROOT}/package/data/"
  find "${PACKAGE_ROOT}/package" -type d -name "__pycache__" -prune -exec rm -rf {} +
  find "${PACKAGE_ROOT}/package" -type f -name "*.pyc" -delete
  (
    cd "${PACKAGE_ROOT}/package"
    zip -r ../lambda-package.zip .
  )
}

build_package .build/runtime314 3.14
build_package .build/runtime313 3.13
```

Then from `infra/`:

```bash
terraform init
terraform plan -var-file=sandbox.tfvars
```

Current package ownership:

- `lambda_package_path`
  - defaults to `../.build/runtime314/lambda-package.zip`
  - used by the existing 3.14-backed webhook ingress / worker / manual sync Lambdas during local packaging flows
- `runtime313_lambda_package_path`
  - defaults to `../.build/runtime313/lambda-package.zip`
  - used by the 3.13-backed OAuth, OAuth refresh and binding coverage check Lambdas

When adopting the current live stack, make sure these variables match the IAM role names AWS already assigned to the Lambdas:

- `webhook_ingress_lambda_role_name`
- `worker_lambda_role_name`
- `manual_count_sync_lambda_role_name`

Without that, Terraform will assume it should create replacement roles with clean names, which is not what you want for a safe import-first rollout.

For the new OAuth slice, Terraform also expects:

- `square_oauth_client_id`
- `square_oauth_client_secret`
- `square_oauth_redirect_uri`

Those are required for the deployed callback flow and should be supplied through your local ignored `sandbox.tfvars`.

## OAuth Bootstrap Sequence

Because the dedicated OAuth API is a new resource, the final deployed callback URL does not exist until after the first Terraform apply.

That means OAuth setup is a two-step bootstrap:

1. Put the Square sandbox application credentials into local `sandbox.tfvars`.
2. Use a temporary `square_oauth_redirect_uri` value for the first apply.
3. Run `terraform apply` to create the OAuth API, OAuth Lambda, and OAuth state table.
4. Read the generated `oauth_callback_url` Terraform output.
5. Update both:
   - the Square Sandbox Redirect URL in the Square Developer Dashboard
   - `square_oauth_redirect_uri` in local `sandbox.tfvars`
6. Run `terraform apply` again so the deployed Lambda config and Square app configuration match exactly.

Until that second apply is complete, the deployed OAuth callback should be treated as not fully wired.

## Runtime Compatibility Note

The live webhook ingress, worker and manual count sync Lambdas run `python3.14`; the OAuth, OAuth refresh and binding coverage check Lambdas run `python3.13`. The Terraform AWS provider version used by this scaffold currently validates Lambda runtimes only through `python3.13`.

To keep planning and import safe:

- the scaffold defaults `lambda_runtime` to `python3.13`
- every Lambda resource except OAuth (which is on `python3.13`) ignores runtime drift

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
- both queues ignore `visibility_timeout_seconds` drift, so changing the variable does not change the live queue; apply that change with `aws sqs set-queue-attributes` too
- the merchant bindings table is modeled as a hash-only table, matching the live schema

That reduces noisy drift and avoids dangerous replacement of the bindings table during import.

## One-time migration: environment-scoped rule and alarm names

Both workspaces' states track the same physical binding-coverage rule, its target and 4 alarms. Sandbox must forget them before it ever applies, or it would delete resources prod depends on. Run each step from `infra/` on the merged commit. Check `terraform workspace show` before every plan or apply. Do not apply if a plan differs from what is described.

1. **Back up both states.** Keep the backups outside the repo; they contain secrets.
   ```
   mkdir -p ~/tf-backups
   terraform workspace select default
   terraform state pull > ~/tf-backups/sandbox-pre-suffix.tfstate
   terraform workspace select production
   terraform state pull > ~/tf-backups/production-pre-suffix.tfstate
   ```
2. **Sandbox: forget the shared resources.** Do not remove `aws_lambda_permission.allow_binding_coverage_check_schedule`; it belongs to the sandbox function. Keep it in state on purpose: if you removed it, a later sandbox apply would try to create the same `statement_id` on the sandbox function, which already has it, and fail with `ResourceConflictException`.
   ```
   terraform workspace select default
   terraform state rm aws_cloudwatch_event_rule.binding_coverage_check aws_cloudwatch_event_target.binding_coverage_check 'aws_cloudwatch_metric_alarm.binding_coverage_check_errors[0]' 'aws_cloudwatch_metric_alarm.webhook_jobs_dlq_visible_messages[0]' 'aws_cloudwatch_metric_alarm.webhook_jobs_oldest_message_age[0]' 'aws_cloudwatch_metric_alarm.webhook_worker_errors[0]'
   ```
3. **Production: plan and apply.**
   ```
   terraform workspace select production
   terraform plan -var-file=production.tfvars -out suffix-prod.tfplan
   ```
   Expected plan:
   - The 2 rules show `+/-` (create before destroy), with new names ending in `-prod`.
   - The 2 targets and 5 alarms show `-/+` (destroy, then create), with new names ending in `-prod`.
   - The 2 lambda permissions show `-/+`, because source_arn changes.
   - About 11 to add, 0 to change, 11 to destroy.

   Stop if anything else appears. Then run:
   ```
   terraform apply suffix-prod.tfplan
   ```
4. **Verify prod** (read-only).
   ```
   aws events list-rules --name-prefix mosa-tea --query 'Rules[].Name'
   aws events list-targets-by-rule --rule mosa-tea-oauth-refresh-prod
   aws events list-targets-by-rule --rule mosa-tea-binding-coverage-check-prod
   aws cloudwatch describe-alarms --alarm-name-prefix mosa-tea --query 'MetricAlarms[].AlarmName'
   ```
   Only the `-prod` rules and alarms should exist (the unsuffixed ones are gone), and each target ARN should end in `-prod`.
5. **Sandbox: no apply in this migration.** After step 2, sandbox state holds no rules, targets or alarms. It still tracks `allow_binding_coverage_check_schedule`, whose `source_arn` now names the deleted unsuffixed rule (harmless). Sandbox loses nothing real, because the shared rule and alarms point at `-prod` resources today (prod applied last).

   The sandbox copies, all named `-sandbox`, are created later, as a deliberate, separate task that reconciles sandbox drift. The known drift that task must handle:
   - creating the usage-log table (`aws_dynamodb_table.usage_log`);
   - Lambda timeout and environment updates (`binding_coverage_check`, `webhook_worker`, the ingress Lambda);
   - an IAM policy change;
   - creating the sandbox oauth-refresh Lambda, role and log group;
   - re-enabling `aws_lambda_event_source_mapping.webhook_worker_queue`, which is disabled on purpose. The sandbox queue's 30 s visibility timeout is below the 90 s claim lease.

   Do NOT run `terraform apply` in `default` until that reconciliation is done. Even a `-target`ed apply of only the rules and alarms pulls in Lambda and table dependencies.
6. **Final check.**
   - Production: the plan should show No changes.
     ```
     terraform workspace select production
     terraform plan -var-file=production.tfvars
     ```
   - Sandbox: plan read-only and do NOT apply it.
     ```
     terraform workspace select default
     terraform plan -var-file=sandbox.tfvars
     ```
     For rules, targets, schedule permissions and alarms, expect only:
     - creates of `aws_cloudwatch_event_rule.binding_coverage_check`, `aws_cloudwatch_event_rule.oauth_refresh`, `aws_cloudwatch_event_target.binding_coverage_check`, `aws_cloudwatch_event_target.oauth_refresh`, and the 5 `aws_cloudwatch_metric_alarm` resources, every name ending in `-sandbox`;
     - a create of `aws_lambda_permission.allow_oauth_refresh_schedule`;
     - one replace (`-/+`): `aws_lambda_permission.allow_binding_coverage_check_schedule`, whose `source_arn` moves from the deleted unsuffixed rule to the `-sandbox` rule.

     No name may end in `-prod` or be unsuffixed, and nothing else in this set may be destroyed or replaced. Other drift is expected and out of scope (see step 5). Do not apply.
   - Repeat the step 4 AWS checks: only the `-prod` rules and alarms exist.

**Rollback:** if sandbox has been applied since the migration (it holds `-sandbox` rules or alarms; check with `terraform workspace select default`, then `terraform state list`, and look for `aws_cloudwatch_event_rule.` or `aws_cloudwatch_metric_alarm.` entries), first destroy them in `default`:
```
terraform workspace select default
terraform destroy -var-file=sandbox.tfvars -target=aws_cloudwatch_event_rule.binding_coverage_check -target=aws_cloudwatch_event_target.binding_coverage_check -target=aws_lambda_permission.allow_binding_coverage_check_schedule -target=aws_cloudwatch_event_rule.oauth_refresh -target=aws_cloudwatch_event_target.oauth_refresh -target=aws_lambda_permission.allow_oauth_refresh_schedule -target='aws_cloudwatch_metric_alarm.webhook_jobs_dlq_visible_messages[0]' -target='aws_cloudwatch_metric_alarm.webhook_jobs_oldest_message_age[0]' -target='aws_cloudwatch_metric_alarm.webhook_worker_errors[0]' -target='aws_cloudwatch_metric_alarm.oauth_refresh_errors[0]' -target='aws_cloudwatch_metric_alarm.binding_coverage_check_errors[0]'
```
Then `git revert` the change and repeat step 3 (production) only. Never apply sandbox on the reverted code: its unsuffixed names would upsert prod's rules and alarms and repoint them at sandbox. If a state is damaged, restore it with `terraform state push -force ~/tf-backups/<file>`.

## Notes

- The Terraform scaffold uses one shared Lambda package per Python runtime (3.14 and 3.13), matching the current GitHub Actions deploy model.
- Terraform ignores Lambda package/hash drift for all six functions, so infra-only applies do not accidentally redeploy code when the local build artifact differs from what is live in AWS.
- It parameterizes sensitive values but does not store them.
- It now includes a dedicated OAuth state table with TTL for short-lived callback state.
- The OAuth API is intentionally separate from the webhook API and manual sync API to keep automation ingress, reconciliation tooling, and auth/onboarding concerns modular.
