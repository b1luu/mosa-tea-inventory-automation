# Ops Runbook

This runbook is for operator response to alarms and inventory incidents. It assumes:

- a local checkout of this repo
- AWS CLI access to the production account
- the repo environment configured well enough to run the existing scripts

### DLQ has messages

**When this fires:** the `mosa-tea-webhook-jobs-dlq-visible-messages` alarm fired because at least one webhook job was redriven to the dead-letter queue.

**Diagnose:**

```bash
aws sqs receive-message \
  --queue-url "$(terraform -chdir=infra output -raw webhook_jobs_dlq_url)" \
  --max-number-of-messages 10 \
  --visibility-timeout 30 \
  --wait-time-seconds 1
```

```bash
aws --no-cli-pager logs tail /aws/lambda/mosa-tea-webhook-worker --since 30m
```

```bash
./.venv/bin/python -m scripts.list_order_processing_states failed
```

**Recover:**

1. Fix the root cause first. Common causes are bad recipe data, missing binding coverage, or an expired merchant OAuth token.
2. Replay the affected order after the fix:

```bash
./.venv/bin/python -m scripts.replay_order ORDER_ID
```

3. Remove the poison message from the DLQ after the replay succeeds:

```bash
./.venv/bin/python -m scripts.delete_sqs_job_by_order_id ORDER_ID
```

**Escalate to engineering when:** the same order returns to the DLQ after replay, or worker logs show a code exception rather than a merchant-data problem.

### Main queue is aging

**When this fires:** the `mosa-tea-webhook-jobs-oldest-message-age` alarm fired because the oldest visible webhook job has been waiting too long in the main queue.

**Diagnose:**

```bash
aws sqs get-queue-attributes \
  --queue-url "$(terraform -chdir=infra output -raw webhook_jobs_queue_url)" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible ApproximateAgeOfOldestMessage
```

```bash
aws --no-cli-pager lambda list-event-source-mappings \
  --function-name mosa-tea-webhook-worker
```

```bash
aws --no-cli-pager logs tail /aws/lambda/mosa-tea-webhook-worker --since 30m
```

**Recover:**

1. If the event source mapping is disabled or stuck, re-enable it in the AWS Console.
2. If the worker is throttled or not invoking, raise reserved concurrency or clear the throttle condition in the AWS Console.
3. If the worker deployment is unhealthy, redeploy the worker Lambda from the current good `main` state.

**Escalate to engineering when:** the event source mapping is enabled and the queue still does not drain, or the logs suggest a platform or deploy regression rather than a single bad order.

### Worker Lambda errors

**When this fires:** the `mosa-tea-webhook-worker-errors` alarm fired because the worker Lambda emitted one or more errors in a five-minute window.

**Diagnose:**

```bash
aws --no-cli-pager logs tail /aws/lambda/mosa-tea-webhook-worker --since 30m
```

```bash
aws --no-cli-pager lambda get-function-configuration \
  --function-name mosa-tea-webhook-worker
```

```bash
./.venv/bin/python -m scripts.list_order_processing_states failed
```

**Recover:**

1. If the failure is data-driven, fix the underlying data issue and replay the affected order:

```bash
./.venv/bin/python -m scripts.replay_order ORDER_ID
```

2. If the failure is a code regression, revert or fix the code and redeploy the worker Lambda from `main`.

**Escalate to engineering when:** the error pattern affects many orders at once, or the fix requires a code change or deploy.

### Binding coverage alarm

**When this fires:** the daily binding coverage check published an SNS alert because a merchant has blocking binding issues, unmapped live variations, or the coverage Lambda failed to evaluate a merchant.

**Diagnose:**

```bash
aws --no-cli-pager logs tail /aws/lambda/mosa-tea-binding-coverage-check --since 30m
```

```bash
./.venv/bin/python -m scripts.show_merchant_setup \
  --environment production \
  --merchant-id MERCHANT_ID
```

```bash
./.venv/bin/python -m scripts.build_binding_coverage_report \
  --environment production \
  --merchant-id MERCHANT_ID \
  --location-id LOCATION_ID
```

**Recover:**

1. If the alert is for a new sellable menu item, add the recipe to `data/recipe_map.json` and ship that change.
2. Upsert the binding update:

```bash
./.venv/bin/python -m scripts.upsert_merchant_catalog_binding \
  --environment production \
  --merchant-id MERCHANT_ID \
  --location-id LOCATION_ID \
  --version VERSION \
  --mapping-file PATH_TO_MAPPING_JSON
```

3. Approve the new binding version if it should become active:

```bash
./.venv/bin/python -m scripts.approve_merchant_catalog_binding \
  --environment production \
  --merchant-id MERCHANT_ID \
  --location-id LOCATION_ID \
  --version VERSION
```

4. Re-run the scheduled coverage Lambda manually to confirm the merchant is clean:

```bash
aws lambda invoke \
  --function-name mosa-tea-binding-coverage-check \
  /tmp/binding_coverage_check.json
cat /tmp/binding_coverage_check.json
```

**Escalate to engineering when:** the issue requires a new recipe or code/data deploy, or the coverage Lambda itself is failing instead of reporting merchant findings.

### Inventory counts look wrong

**When this fires:** an operator reports that Square inventory counts do not match store reality. This does not have a dedicated alarm.

**Diagnose:**

```bash
./.venv/bin/python -m scripts.inspect_order ORDER_ID
```

```bash
./.venv/bin/python -m scripts.list_order_processing_states | rg ORDER_ID -C 3
```

```bash
./.venv/bin/python -m scripts.inspect_inventory_count --inventory-key INVENTORY_KEY
```

**Recover:**

1. If the order processing state is `applied` but the counts are still wrong, treat it as recipe-data drift and correct the count through the Google Sheets manual sync flow.
2. If the order is `blocked`, `failed`, or missing from processing state output, investigate binding coverage, OAuth health, and queue alarms before replaying the order.

**Escalate to engineering when:** a count discrepancy repeats after manual sync, or applied orders consistently project the wrong usage for the same drink.

### OAuth refresh fails

**When this fires:** the worker logs show auth or token-refresh failures while attempting merchant-scoped Square API calls.

**Diagnose:**

```bash
./.venv/bin/python -m scripts.show_merchant_setup \
  --environment production \
  --merchant-id MERCHANT_ID
```

```bash
aws --no-cli-pager logs tail /aws/lambda/mosa-tea-oauth --since 30m
```

```bash
aws --no-cli-pager logs tail /aws/lambda/mosa-tea-webhook-worker --since 30m
```

**Recover:**

1. Get the deployed OAuth reconnect URL:

```bash
terraform -chdir=infra output -raw oauth_start_url
```

2. Have the merchant complete the reconnect flow in the browser.
3. Confirm the merchant record is healthy again:

```bash
./.venv/bin/python -m scripts.show_merchant_setup \
  --environment production \
  --merchant-id MERCHANT_ID
```

4. Re-enable writes if readiness is satisfied but operator intent is still disabled:

```bash
./.venv/bin/python -m scripts.enable_merchant_writes \
  --environment production \
  --merchant-id MERCHANT_ID
```

**Escalate to engineering when:** reconnect succeeds but the merchant record still lacks a usable refresh token, or writes cannot be re-enabled after a successful reconnect.

### Recipe validator fails in CI

**When this fires:** the CI job fails in the recipe validation step because `scripts.validate_recipe_map` found schema errors.

**Diagnose:**

```bash
./.venv/bin/python -m scripts.validate_recipe_map
```

```bash
bash ./scripts/sanity_check.sh
```

**Recover:**

1. Read the validator output. It reports the exact path and offending value.
2. Fix the recipe data or binding data that triggered the validator.
3. Re-run the same local commands before pushing again.

**Escalate to engineering when:** the validator output appears incorrect for valid data, or the failure is caused by validator logic rather than recipe content.
