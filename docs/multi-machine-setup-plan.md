# Multi-Machine Setup Plan

> **Status: to do.** Findings checked against the repo and AWS on 2026-10-21
> (read-only; nothing changed). Goal: work on this repo from both the MacBook
> and a desktop without the two machines fighting over infrastructure.

## Findings

| Question | Answer |
|---|---|
| Git repo with a remote? | **Yes.** Private: `b1luu/mosa-tea-inventory-automation`. The desktop just clones it. |
| Anything sensitive committed, now or in history? | **No.** No `.tfstate`, `.tfvars`, `.tfplan` or real `.env` was ever tracked (only `.env.example`, which has placeholders). No Square tokens, Square app secrets or AWS keys anywhere in history. |
| `.gitignore` | Already covers `.env*`, `infra/*.tfstate*`, `*.tfvars`, `*.tfplan`, `infra/.terraform/`, `.build/`, `__pycache__/`, local `.db` files, `*.pem`/`*.key`. Nothing to add. |
| Terraform state | **Local, two workspaces:** `default` (sandbox, `infra/terraform.tfstate`, 59 resources) and `production` (`infra/terraform.tfstate.d/production/terraform.tfstate`, 78 resources). No backend block. |
| Secrets in state | **Yes, plain text** in Lambda environment variables: `OPERATOR_API_TOKEN`, `OPERATOR_SESSION_SIGNING_KEY`, `SQUARE_OAUTH_CLIENT_SECRET`, `SQUARE_WEBHOOK_SIGNATURE_KEY`, `SQUARE_ACCESS_TOKEN`. The remote state bucket must be private, encrypted and versioned. |
| Config and secrets loading | `app/config.py` calls `load_dotenv()`: environment variables plus `.env`. Production Lambdas get theirs from Terraform; merchant OAuth tokens live in Secrets Manager (`mosa-tea-prod/merchant-auth/...`). |
| Machine architecture | **Both machines are x86_64.** The MacBook is Intel (no arm64 capability), not Apple Silicon. Nothing needs to be architecture-aware. |
| Python | **3.14** (venv, CI; worker, ingress, count sync Lambdas) and **3.13** (OAuth, coverage check, OAuth refresh Lambdas). **Not 3.12.** Pinned only in the GitHub workflows; no `.python-version`. |
| Python packages | `requirements.txt`, exact pins. Only compiled dependency: `pydantic_core` (via `squareup`). |
| Terraform | **1.14.8** in use; `required_version = ">= 1.6.0"` (loose). AWS provider **5.100.0**, pinned by the committed `.terraform.lock.hcl`. |
| Lambda packaging | `pip install --platform manylinux2014_x86_64 --only-binary=:all:` into `.build/runtime314` and `.build/runtime313`, so the build machine's architecture never matters. All Lambdas target **x86_64**. Real deploys run in GitHub Actions (`deploy-lambda.yml`). |
| Machine-specific bits | Almost none: no hard-coded AWS profile (only `default` exists), no macOS-only commands in scripts. One absolute path in a doc (`docs/operator-recount-workflow.md:61`). |

## Gotchas for a fresh machine

- **`terraform plan` fails on a fresh clone** until `.build/runtime314/lambda-package.zip`
  and `.build/runtime313/lambda-package.zip` exist: `infra/lambda.tf` calls
  `filebase64sha256()` on them. Build them first (see `docs/terraform-infrastructure.md`).
- **`.build/` is ~300 MB of local artifacts.** Gitignored; rebuilt per machine.
- **The `.tfvars` files are the only copy of several secrets outside AWS.** They are
  not in git and must be carried over deliberately.

## To do

### 1. Move Terraform state to S3 (do first)

Without shared state, each machine believes it owns the infrastructure.

- [ ] Create the state bucket **outside** this Terraform config (AWS CLI or a tiny
      separate config), so the state never manages its own storage: versioning on,
      default encryption on, all public access blocked.
- [ ] Back up both local state files (`terraform.tfstate` and
      `terraform.tfstate.d/production/terraform.tfstate`) somewhere safe.
- [ ] Add a `backend "s3"` block with `use_lockfile = true` (Terraform's built-in S3
      locking, 1.10+; no DynamoDB lock table needed).
- [ ] `terraform init -migrate-state`. It copies **both** workspaces; non-default ones
      land under `env:/production/...`.
- [ ] In **each** workspace, `terraform plan` must show **no changes**. This is the
      proof that nothing was recreated or orphaned. Stop if it shows anything.
- [ ] Only then delete the local state files and backups.

### 2. Clean up local secrets

- [ ] Delete the 10 stale `infra/*.tfplan` files. Plan files embed variable values,
      so they contain secrets.
- [ ] Remove `AWS_ACCESS_KEY` / `AWS_SECRET_KEY` from `.env`. No code reads them (and
      boto3 doesn't use those names), so they are an unused long-lived key on disk.
      Deactivate the key in IAM if nothing else uses it.
- [ ] Store `infra/production.tfvars`, `infra/sandbox.tfvars` and `.env` in a password
      manager rather than copying files between machines.

### 3. Pin versions so both machines match

- [ ] Add `.python-version` containing `3.14`.
- [ ] Tighten Terraform to `required_version = "~> 1.14.0"` (and use `tfenv` or the
      same install on both machines).
- [ ] Fix the absolute path in `docs/operator-recount-workflow.md:61`.

### 4. Bootstrap the desktop

Depends on the desktop's OS (**open question**).

- **macOS or Linux (simpler, recommended):** a short bootstrap script or Makefile:
  - `make setup`: create the venv with `uv` from `.python-version` and `requirements.txt`;
  - `make build`: build both Lambda zips with the documented `build_package` steps.
- **Windows:** a Dev Container is worth it: Python 3.14, Terraform 1.14.8 and AWS CLI v2,
  with `~/.aws` mounted through WSL. Single-architecture (x86_64) is enough.

Then on the desktop:

- [ ] `git clone`, `gh auth login`
- [ ] AWS credentials in `~/.aws` (`default` profile)
- [ ] Pull `.tfvars` files and `.env` from the password manager
- [ ] Run setup and build; `terraform init` (S3 backend); `terraform plan` shows no changes

### Later (not needed now)

- SAM CLI or LocalStack for running Lambdas locally.
- Moving `.tfvars` secrets into SSM Parameter Store / Secrets Manager so Terraform reads
  them instead of local files.

## Open question

- **What OS is the desktop?** Decides step 4 (bootstrap script vs Dev Container).
