# Production stack rollout runbook

Step-by-step playbook for bringing up the production OAuth onboarding stack
(Lambda + API Gateway + DynamoDB + Secrets) alongside the existing sandbox
stack in the same AWS account. Follow this end-to-end the first time. After
the production stack exists, subsequent code-only changes deploy via the
`Deploy Lambda Functions` GitHub Actions workflow with `environment=production`
— this runbook is only for the **initial bring-up**.

> Related but distinct: [`production-onboarding-runbook.md`](production-onboarding-runbook.md)
> covers the operator-facing onboarding flow (the boss clicking through OAuth).
> This document covers the infrastructure that hosts that flow.

## Preconditions

Before starting, confirm every item:

- [ ] Both `PR #2a` (deploy-workflow environment input) and `PR #2b` (this
      runbook + `production.tfvars.example`) are merged to `main`.
- [ ] Production Square OAuth credentials are in hand: `client_id` and
      `client_secret` from the Square Developer Dashboard → your app →
      **Production** tab (NOT the sandbox tab).
- [ ] Local `terraform` and `aws` CLIs work; `aws sts get-caller-identity`
      returns the correct account.
- [ ] You are on `main`, up to date: `git checkout main && git pull --ff-only`.
- [ ] The sandbox stack is currently healthy (so a problem during the
      production rollout doesn't get conflated with pre-existing sandbox
      issues).

## Naming convention (read this once)

Every production resource name ends with `-prod`. The full set of names lives
in `infra/production.tfvars` and is mirrored by 5 `PROD_*` GitHub repository
variables that the deploy workflow reads. **Never mix `-prod` resource names
with the sandbox Terraform workspace, or unsuffixed names with the production
workspace.** Always run `terraform workspace show` before any apply.

## Known gotchas (read this once)

Two oddities of this stack to be aware of going in. Both are tracked for a
follow-up cleanup PR; the runbook + template work around them.

1. **`terraform.tfvars` auto-loads even when `-var-file=production.tfvars`
   is set.** Terraform reads `infra/terraform.tfvars` (sandbox values)
   automatically, then applies your `-var-file` on top. For any variable
   set in sandbox but NOT in `production.tfvars`, the sandbox value silently
   leaks into the production plan. The provided `production.tfvars.example`
   already overrides every leaky key we know about — keep it that way when
   editing. If you ever add a new variable to sandbox, add it to both
   examples.

2. **Three CloudWatch alarm names are not workspace-suffixed.** Specifically
   `mosa-tea-binding-coverage-check-errors`,
   `mosa-tea-webhook-jobs-dlq-visible-messages`,
   `mosa-tea-webhook-jobs-oldest-message-age`, and
   `mosa-tea-webhook-worker-errors`. CloudWatch alarm names are globally
   unique per AWS account, and `PutMetricAlarm` is UPSERT. On the first
   production apply these alarms get hijacked from sandbox — production
   takes ownership and the alarms start watching production Lambdas/queues.
   This is harmless for production but **leaves sandbox temporarily
   un-alarmed**. The fix (workspace-suffixed names) is a separate PR.

---

## Step 1 — Generate fresh production secrets

Run each command and save the output in a password manager. **Do not reuse
sandbox values.**

```bash
python -c "import secrets; print('operator_api_token =', secrets.token_urlsafe(32))"
python -c "import secrets; print('operator_session_signing_key =', secrets.token_urlsafe(32))"
```

You will paste these into `production.tfvars` in Step 2.

## Step 2 — Create `infra/production.tfvars`

```bash
cd infra
cp production.tfvars.example production.tfvars
```

Open `production.tfvars` and fill in real values for each `replace_me_*`
placeholder:

| Field | Source |
|---|---|
| `square_oauth_client_id` | Square Developer Dashboard → app → Production tab |
| `square_oauth_client_secret` | Square Developer Dashboard → app → Production tab |
| `operator_api_token` | Step 1 output |
| `operator_session_signing_key` | Step 1 output |
| `square_webhook_signature_key` | Placeholder okay for now (no production webhook yet); replace before enabling production webhooks |
| `square_oauth_redirect_uri` | Leave as `PLACEHOLDER_replace_after_first_apply`; filled in Step 5 |
| `square_access_token` | Leave as `unused_in_production` (PAT is not used in production) |

`production.tfvars` is gitignored. Never commit it.

## Step 3 — Create the production Terraform workspace

```bash
cd infra
terraform workspace new production
terraform workspace show   # MUST print: production
```

The current `default` workspace remains tied to the sandbox stack. The new
`production` workspace has its own state file under
`terraform.tfstate.d/production/` and starts empty.

## Step 4 — First `terraform apply` (creates the production stack)

```bash
terraform plan -var-file=production.tfvars -out production.tfplan
```

**Read the plan carefully before applying.** Expectations:

- ~30+ resources being **created** (Lambda functions, IAM roles, DynamoDB
  tables, API Gateway, SQS queues, CloudWatch alarms)
- **Zero** resources being destroyed
- **Zero** resources being modified

If the plan shows anything destroyed or modified, **stop** — you are on the
wrong workspace. Run `terraform workspace show` and switch to `production`
before retrying.

When the plan is clean:

```bash
terraform apply production.tfplan
```

Apply takes a few minutes. When it finishes, **note the outputs** — especially
`oauth_callback_url`. Copy it.

## Step 5 — Update Square's production redirect URI + re-apply

1. In Square Developer Dashboard → your app → **Production** tab → OAuth
   section, paste the `oauth_callback_url` from Step 4 into the **Redirect
   URL** field. Save.
2. Open `infra/production.tfvars` and replace the placeholder:
   ```
   square_oauth_redirect_uri = "<paste the oauth_callback_url from Step 4>"
   ```
3. Re-plan + re-apply:
   ```bash
   terraform plan -var-file=production.tfvars -out redirect-uri.tfplan
   terraform apply redirect-uri.tfplan
   ```

The plan should show exactly **one change**: the `SQUARE_OAUTH_REDIRECT_URI`
env var on the production OAuth Lambda. If it shows more, stop and
investigate.

## Step 6 — Add `PROD_*` GitHub repository variables

GitHub → repository → Settings → Secrets and variables → Actions → **Variables**
tab → New repository variable. Add all 5:

| Variable name | Value |
|---|---|
| `PROD_WORKER_LAMBDA_FUNCTION_NAME` | `mosa-tea-webhook-worker-prod` |
| `PROD_WEBHOOK_INGRESS_LAMBDA_FUNCTION_NAME` | `mosa-tea-webhook-ingress-prod` |
| `PROD_MANUAL_COUNT_SYNC_LAMBDA_FUNCTION_NAME` | `mosa-tea-manual-count-sync-prod` |
| `PROD_OAUTH_LAMBDA_FUNCTION_NAME` | `mosa-tea-oauth-prod` |
| `PROD_BINDING_COVERAGE_CHECK_LAMBDA_FUNCTION_NAME` | `mosa-tea-binding-coverage-check-prod` |

The values must match the function names in `production.tfvars` exactly.

## Step 7 — Deploy code to production Lambdas

GitHub → Actions → **Deploy Lambda Functions** → Run workflow:
- Branch: `main`
- Environment: **production**
- Click Run workflow

The workflow run will start with a yellow banner: *"Production deploy selected.
This affects real merchant traffic."*

If the run fails on the validation step with *"Production deploy requires
these GitHub repository variables to be set: …"*, you missed one of the vars
in Step 6. Add it and re-run.

## Step 8 — Sanity-check the production Lambda

```bash
aws lambda get-function-configuration \
  --function-name mosa-tea-oauth-prod \
  --region us-west-2 \
  --query 'Environment.Variables.SQUARE_OAUTH_SCOPES' \
  --output text
```

Expected: a 6-scope string ending in `,ITEMS_WRITE`.

```bash
aws lambda get-function-configuration \
  --function-name mosa-tea-oauth-prod \
  --region us-west-2 \
  --query 'Environment.Variables.SQUARE_ENVIRONMENT' \
  --output text
```

Expected: `production`.

## Step 9 — Run the production OAuth flow against the real merchant

Get the production onboarding URL:

```bash
echo "https://$(aws apigatewayv2 get-apis --region us-west-2 \
  --query 'Items[?Name==`mosa-tea-oauth-api-prod`].ApiId' \
  --output text).execute-api.us-west-2.amazonaws.com/onboarding"
```

Open it in a fresh incognito window. Then:

1. Paste the **production** operator API token from Step 1 (not the sandbox
   one) → Continue.
2. Click **Connect to Square**.
3. **Sign in as the real Mosa Tea merchant account** (the actual shop's Square
   dashboard login — not the sandbox test account).
4. On Square's consent screen, verify **6 scopes** are listed, ending with
   *"Modify your item library"*. Click **Allow**.
5. The Connected success page must show:
   - **MERCHANT**: the real Mosa Tea shop name (NOT "Default Test Account").
   - **MERCHANT ID**: the real production merchant ID.
   - **ENVIRONMENT**: `production`.
   - **PERMISSIONS GRANTED**: 6 bullets, ending with `ITEMS_WRITE`.

## Verification checklist

- [ ] Step 8 commands return expected values.
- [ ] Real merchant ID is stored in the `mosa-tea-merchant-connections-prod`
      DynamoDB table:
      ```bash
      aws dynamodb scan --table-name mosa-tea-merchant-connections-prod \
        --region us-west-2 --limit 5
      ```
- [ ] Production CloudWatch log group `/aws/lambda/mosa-tea-oauth-prod` has
      `GET /onboarding`, `POST /onboarding`, `GET /oauth/square/start`, and
      `GET /oauth/square/callback` entries.
- [ ] **Sandbox is still healthy**: open the sandbox `/onboarding` URL, paste
      sandbox operator token, confirm the Connect page still loads. Production
      rollout must not have broken sandbox.

---

## Troubleshooting

### "Wrong workspace" during apply

Symptom: `terraform plan` shows resources being destroyed or modified when you
expected a clean creation.

Cause: you are on the wrong workspace.

Recovery:
```bash
terraform workspace show
terraform workspace select production
terraform plan -var-file=production.tfvars
```

Do not run `terraform apply` until `workspace show` prints the expected
environment.

### Apply failed mid-way

Terraform is idempotent. Re-run `terraform plan + apply` with the same
tfvars; it will create whatever's missing and leave the rest alone.

### OAuth flow blank-page or error on production

Most likely: redirect URI mismatch.

Verify all three values match exactly:
1. The `oauth_callback_url` output from `terraform output -json`.
2. Square Developer Dashboard → Production tab → Redirect URL.
3. `SQUARE_OAUTH_REDIRECT_URI` env var on the production OAuth Lambda:
   ```bash
   aws lambda get-function-configuration --function-name mosa-tea-oauth-prod \
     --region us-west-2 --query 'Environment.Variables.SQUARE_OAUTH_REDIRECT_URI' \
     --output text
   ```

### Production workflow validation rejects with missing vars

You missed a `PROD_*` repo variable in Step 6. The error message lists which
ones. Add them and re-run.

---

## Future maintenance

When a future PR adds a new Lambda function:

1. Add the function name variable in [`infra/variables.tf`](../infra/variables.tf).
2. Add the new line to both [`infra/terraform.tfvars.example`](../infra/terraform.tfvars.example)
   (sandbox naming) and [`infra/production.tfvars.example`](../infra/production.tfvars.example)
   (with `-prod` suffix).
3. In [`.github/workflows/deploy-lambda.yml`](../.github/workflows/deploy-lambda.yml):
   - Add a new line in the `env:` block with the
     `inputs.environment == 'production' && vars.PROD_X || vars.X` ternary.
   - Add the new `PROD_X` to the validation loop's `MISSING` check.
   - Add a `deploy_function "${X_LAMBDA_FUNCTION_NAME}" ...` call in the
     deploy step.
4. After merge, add the matching `PROD_X_LAMBDA_FUNCTION_NAME` GitHub
   repository variable (Step 6 of this runbook).
5. `terraform apply -var-file=production.tfvars` to create the new prod
   resources, then trigger the workflow with `environment=production` to
   deploy code.
