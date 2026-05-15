# CloudWatch Alarm Smoke Test

Use this after applying the baseline CloudWatch alarms to verify:

- the DLQ alarm enters `ALARM`
- SNS notification delivery works
- the DLQ alarm returns to `OK`
- Terraform is converged after the rollout

## Preconditions

- `alarm_notification_topic_arn` is set in local ignored `infra/terraform.tfvars`
- the SNS email subscription is confirmed
- Terraform apply has already completed successfully

## 1. Confirm alarm names and queue URL

```bash
terraform -chdir=infra output cloudwatch_alarm_names
terraform -chdir=infra output webhook_jobs_dlq_url
```

## 2. Send a synthetic message to the DLQ

```bash
aws sqs send-message \
  --queue-url "$(terraform -chdir=infra output -raw webhook_jobs_dlq_url)" \
  --message-body '{"canary":true,"reason":"manual cloudwatch alarm test"}'
```

## 3. Wait about 90 seconds, then check the DLQ alarm

```bash
aws cloudwatch describe-alarms \
  --alarm-names "mosa-tea-webhook-jobs-dlq-visible-messages" \
  --query 'MetricAlarms[0].{State:StateValue,Reason:StateReason,Updated:StateUpdatedTimestamp}' \
  --output table
```

Expected:

- `State = ALARM`
- SNS notification email received

## 4. Purge the DLQ

```bash
aws sqs purge-queue \
  --queue-url "$(terraform -chdir=infra output -raw webhook_jobs_dlq_url)"
```

SQS purge is eventually consistent. Give it time to propagate.

## 5. Confirm the DLQ is empty

```bash
aws sqs get-queue-attributes \
  --queue-url "$(terraform -chdir=infra output -raw webhook_jobs_dlq_url)" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
```

Expected:

- `ApproximateNumberOfMessages = 0`
- `ApproximateNumberOfMessagesNotVisible = 0`

## 6. Wait about 90 seconds, then check the alarm again

```bash
aws cloudwatch describe-alarms \
  --alarm-names "mosa-tea-webhook-jobs-dlq-visible-messages" \
  --query 'MetricAlarms[0].{State:StateValue,Reason:StateReason,Updated:StateUpdatedTimestamp}' \
  --output table
```

Expected:

- `State = OK`
- SNS recovery notification email received

## 7. Final Terraform convergence check

```bash
terraform -chdir=infra plan -var-file=terraform.tfvars
```

Expected:

- `No changes. Your infrastructure matches the configuration.`
