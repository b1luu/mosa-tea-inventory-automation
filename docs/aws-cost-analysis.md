# AWS Cost Analysis

The current local stack is intentionally lightweight, but the architecture is being refactored toward:
- Lambda for webhook ingress and worker execution
- SQS for job transport
- DynamoDB for webhook event, order-processing, and merchant-auth storage

At the current expected scale, that AWS path should be inexpensive.

## Fermi Estimate: 200 Drinks Per Day

Assumptions:
- `200` completed orders per day
- about `3` Square webhook events per order
  - `order.created`
  - `order.updated` while open
  - `order.updated` when completed
- one SQS-dispatched worker job per completed order
- small JSON payloads

Approximate monthly volume:
- `6,000` completed orders per month
- `18,000` webhook events per month
- about `18,000` SQS requests per month
  - send + receive + delete are all requests
- about `24,000` Lambda invocations per month
  - ingress + worker combined

## Practical Cost Expectation

- SQS:
  - effectively negligible at this scale
- Lambda:
  - likely negligible at this scale
- DynamoDB:
  - likely pennies to very low single-digit dollars unless retention or traffic grows substantially
- API Gateway:
  - small if used, and avoidable if Lambda Function URLs are sufficient

So for this project, the main challenge is architecture and correctness, not raw AWS service cost.
