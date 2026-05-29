# Secrets & Security

> **Scope:** what is sensitive in this project, where it lives, what must never
> reach git, the pre-commit checklist, sanitization rules for public docs, and
> the playbook for a suspected leak. Read this once; pair it with `.gitignore`.

## Threat model in one paragraph

The realistic risk to this project is **accidental commit of a secret to git** —
a `.env` slipping in, a refresh token printed into a fixture, an AWS key pasted
into a script. The deployed system's runtime is well-bounded (OAuth scopes
exclude payments/orders; HMAC-verified webhooks; OIDC for GitHub→AWS), so the
single highest-impact mistake is **not** at runtime — it's a commit that lands a
credential on GitHub. Once it's on GitHub, force-pushing history does not
help — assume compromised, rotate.

## Where each secret lives

| Secret | Where it lives | Surfaces it appears on |
|---|---|---|
| Sandbox personal access token (dev) | Local `.env` only | Local scripts (canary, organize, create) |
| Square OAuth client secret (per environment) | AWS Secrets Manager | OAuth Lambda (code-exchange + refresh) |
| Merchant OAuth access + refresh tokens | DynamoDB `merchant_connections` (refresh token persisted; access token cached/derived) | Worker Lambda, manual-count-sync, binding-coverage cron |
| Square webhook signature key (per environment) | Lambda env var (set from Secrets Manager) | Webhook ingress Lambda |
| AWS deploy role ARN | GitHub repo secret `AWS_ROLE_TO_ASSUME` (OIDC, no long-lived keys) | Deploy + smoke-canary workflows |
| Operator API token | Local `.env` (`OPERATOR_API_TOKEN`); to be set on OAuth-onboarding Lambda env | Operator-gated OAuth onboarding routes |
| GitHub `SQUARE_ACCESS_TOKEN` (sandbox PAT for canary) | GitHub repo secret | Smoke-canary workflow only |

Notably: **no production access token (PAT) exists** — production catalog/inventory
writes go through OAuth-issued tokens stored encrypted in Secrets Manager +
DynamoDB.

## What never gets committed

- Any access token, refresh token, client secret, signature key.
- Real merchant data — production catalog snapshots, real customer info, order
  payloads from real shoppers.
- AWS credentials (`.aws/`, IAM access keys, session tokens).
- Per-account runtime artifacts — backup files
  (`data/backend_inventory_backups/`), captured-id files
  (`data/backend_inventory_created_ids.json`), local sqlite stores (`*.db`).
- Local config flavours (`.env`, `.env.local`, `.env.production`, etc.).
- Terraform state (`*.tfstate*`) and any plan files (`tfplan*`) — these can hold
  secrets in cleartext.
- Anything that *looks* like a credential by filename — `*.pem`, `*.key`,
  `credentials.json`, `service-account*.json`.

The committed `.gitignore` enforces most of this defensively; the rules above
are the *intent* behind it.

## Pre-commit checklist (do this every time)

1. Run `git status` and `git diff --cached` — read every change, don't trust
   "looks small."
2. Confirm no file named `.env*` (other than `.env.example` if you add one).
3. Confirm no `data/*.json` that contains real-account IDs or counts you didn't
   mean to share. Sandbox-canonical IDs are fine; per-merchant artifacts are not.
4. Confirm no token-looking strings (long random alphanumeric blobs) appear in
   any diff line, especially in scripts or tests.
5. Confirm no AWS account IDs in any file that could become public (docs,
   READMEs). Use the placeholder `123456789012` for public docs.

If any of those fail, **stop, fix, then commit** — don't rely on review or CI to
catch it.

## Sanitization rules for public-facing docs

- **AWS account ID** → use `123456789012` in any doc that could become public.
- **Production merchant ID / location ID** → omit or use a placeholder.
- **Sandbox catalog object IDs** → fine to include; sandbox is throwaway and the
  IDs are public-by-design (they're in `recipe_map.json`, the binding file,
  scenario fixtures, etc.).
- **AWS resource ARNs in runbooks** → keep specific in private/internal runbooks;
  sanitize the account-id segment in anything externally shared.

## If something leaks (the response playbook)

In this order, and **don't skip the rotation step thinking "I'll force-push the
history"** — once it hit GitHub it's reachable.

1. **Rotate first**, before anything else:
   - Square OAuth client secret → Square Developer Dashboard → rotate.
   - Merchant OAuth token (suspected compromise) → `client.o_auth.revoke_token`
     (or merchant revokes in Seller Dashboard) → re-onboard.
   - AWS access keys → IAM console disable + delete; rotate any role that
     trusted them.
   - Webhook signature key → Square Developer Dashboard → rotate → update Lambda
     env via Secrets Manager.
   - Operator API token → regenerate, update `.env` and Lambda env.
2. **Audit usage** — Square API logs, AWS CloudTrail, GitHub audit log — look for
   anything between leak time and rotation time.
3. **Then** clean git: remove the file from the working tree, commit, push;
   optionally use `git filter-repo` to scrub history (but treat the secret as
   already-compromised regardless).
4. **Note it** — append a one-line entry to a private incident log: when, what,
   how detected, when rotated, what was audited.

## Standard account hygiene that bounds the rest

These are not in the repo's control but are the most leverage per minute spent:

- **2FA on:** GitHub, the Square Developer account, the Square seller account,
  AWS root, AWS IAM users.
- **Branch protection on `main`:** require PR review, require status checks,
  no force-push, no direct push.
- **AWS:** MFA on root; prefer SSO/role assumption over long-lived IAM access
  keys; GuardDuty enabled (cheap, high signal).
- **Lock your laptop** when you walk away. Trivial but real.

## Related

- [Production onboarding runbook](production-onboarding-runbook.md) — the full
  OAuth scope justification and the revocation playbook live there.
- [Ops runbook](ops-runbook.md) — operational alarms and what to do.
