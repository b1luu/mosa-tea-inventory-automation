# Documentation

**★ Active priority:** [Catalog binding & production transition](catalog-binding-and-production-transition.md) — the primary open design area for going from a sandbox-backed deployment to a real production merchant.

## Operator workflows

- [Operator recount workflow](operator-recount-workflow.md) — Google Sheet + Apps Script → Square inventory sync
- [Add new ingredient runbook](add-new-ingredient-runbook.md) — end-to-end procedure when the boss adds a new tracked item

## Analysis & interpretation

- [Inventory variance interpretation](inventory-variance-interpretation.md) — what variance means, how to read patterns, calibration ratios

## Architecture & infrastructure

- [API Gateway serverless ingress](api-gateway-serverless-ingress.md)
- [AWS cost analysis](aws-cost-analysis.md)
- [Backend inventory organization](backend-inventory-organization.md)
- [Catalog binding & production transition](catalog-binding-and-production-transition.md)
- [Catalog modifier model](catalog-modifier-model.md)
- [CloudWatch alarm smoke test](cloudwatch-alarm-smoke-test.md)
- [Dependency management](dependency-management.md)
- [Inventory resync design](inventory-resync-design.md) — proposal (updated 2026-10-24): recount cutoff for replays, row-tolerant sheet sync, partial apply, next-recount runbook
- [Multi-machine setup plan](multi-machine-setup-plan.md) — 2026-10-21 to-do: S3 state backend, secrets clean-up, version pins, desktop bootstrap
- [Menu coverage & demand tracking decision](menu-coverage-and-demand-tracking-decision.md) — 2026-10-17: ignore lists, alerting, matcha jelly retirement, oat milk usage log
- [Ops runbook](ops-runbook.md)
- [Order state handling decision](order-state-handling-decision.md)
- [Production onboarding runbook](production-onboarding-runbook.md)
- [Production rollout runbook](production-rollout-runbook.md)
- [Secrets & security](secrets-and-security.md)
- [Production OAuth decision](production-oauth-decision.md)
- [SQS dead-letter queue behavior](sqs-dlq-behavior.md)
- [Terraform infrastructure](terraform-infrastructure.md)
