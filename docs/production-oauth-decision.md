# Production OAuth Decision

## Decision

Production OAuth must use a deployed callback flow.

This project will not rely on:

- localhost-only OAuth callbacks
- developer-laptop reauthorization
- manually shared long-lived production access tokens

The production auth model is:

- merchant authorizes through Square OAuth
- Square redirects back to a deployed callback URL
- merchant auth is persisted in shared cloud-backed state
- writes remain disabled until binding and readiness checks pass

## Why This Is Locked In

This product is being built for an owner who:

- is not expected to understand OAuth or cloud deployment details
- is unwilling to hand over a production access token
- needs a recovery path that does not depend on engineering being available

That makes localhost-only OAuth operationally unacceptable, even for a single merchant.

The real constraint is not traffic volume or token lifetime. It is owner operability.

## Decision Gate

The gate for production OAuth is:

**Can the owner re-authorize production without engineering intervention?**

If the answer is no, production OAuth is not ready.

This is the governing gate for future implementation decisions in this area.

## Required Production Behavior

To satisfy that gate, the deployed system must provide all of the following:

1. No laptop dependency
- OAuth start and callback are both deployed
- Square redirect URI points to the deployed callback
- production reauthorization does not require localhost

2. Shared callback state
- OAuth state cannot live only in local SQLite
- state must be available across separate serverless requests and execution environments
- a cloud-backed store is required for the deployed callback path

3. Fail-closed write behavior
- if auth is missing, revoked, or cannot refresh, writes stay disabled
- the system must not guess or continue inventory writes in a degraded auth state

4. Owner-usable recovery
- the owner can follow a simple reconnect flow
- no CLI, no token copy/paste, no AWS console steps

5. Explicit enablement after readiness checks
- auth success alone does not enable writes
- binding, selected location, and readiness checks must still pass before write enablement

## Why The DynamoDB OAuth State Backend Exists

The DynamoDB OAuth state backend exists to support the deployed callback flow.

The state lifetime is short, but that is not the relevant design variable. The relevant variable is deployment topology:

- `/oauth/square/start` and `/oauth/square/callback` are separate requests
- in a deployed serverless model, those requests are not guaranteed to hit the same runtime instance
- filesystem-local SQLite is therefore not a reliable shared store for the deployed callback path

If the project were intentionally staying localhost-only for OAuth forever, SQLite would be sufficient and the cloud backend would be unnecessary.

That is not the chosen product direction.

There is also a consistency and integration reason to keep DynamoDB here:

- DynamoDB is already the project's deployed durable-state backbone
- merchant connections, merchant bindings, webhook events, and order-processing state already follow this pattern
- the codebase already supports the same `sqlite|dynamodb` backend switch model in multiple subsystems
- keeping OAuth callback state in DynamoDB avoids introducing a separate state-management model just for OAuth

So DynamoDB is not being added as a one-off special case. It is an extension of the project's existing cloud-state architecture.

## Consequences

Because this decision is locked in:

- Phase 2 must add a deployed OAuth entrypoint
- Phase 3 must add API Gateway routing and callback exposure
- infrastructure must provision OAuth state storage and env wiring
- localhost OAuth remains useful for local development, but it is not the production recovery model

## Implementation Sequence

1. Keep the OAuth state storage abstraction in place.
2. Add the deployed OAuth Lambda entrypoint.
3. Add API Gateway routes for OAuth start/callback/status/refresh.
4. Provision and wire the cloud-backed OAuth state store.
5. Validate the entire flow in sandbox.
6. Only then enable the production redirect URI and production onboarding path.

## Non-Goals

This decision does not mean:

- production writes should be enabled automatically after OAuth
- engineering no longer needs observability or support tooling
- OAuth infra should be merged before sandbox validation

It only locks in the production auth and reauthorization model.
