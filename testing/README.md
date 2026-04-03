## Testing

This folder holds deterministic test fixtures and tests for the inventory
projection logic.

### Why this exists

The Sandbox order history contains noisy and sometimes unrealistic historical
orders. Instead of relying on live API lookups for every check, this folder
lets you:

- export trusted completed orders into stable JSON fixtures
- keep synthetic modifier-aware cases under version control
- run projection tests locally without mutating Square

### Run tests

```bash
./.venv/bin/python -m unittest discover -s testing -p 'test_*.py'
```

### Preview or run a bulk day profile

Preview the 200-drink peak-day mix:

```bash
./.venv/bin/python -m testing.run_live_order_day_profile sandbox_peak_day_200
```

Preview a smaller mixed canary slice:

```bash
./.venv/bin/python -m testing.run_live_order_day_profile sandbox_canary_mix_40
```

Show the planned order references for a smaller canary slice:

```bash
./.venv/bin/python -m testing.run_live_order_day_profile --limit 20 --show-orders sandbox_peak_day_200
```

Show the staged operational drill commands with queue checkpoints between batches:

```bash
./.venv/bin/python -m testing.run_live_order_day_profile --show-drill sandbox_peak_day_200
```

Show the timed dispatch schedule for a compressed day:

```bash
./.venv/bin/python -m testing.run_live_order_day_profile --show-schedule --schedule-scale 0.1 sandbox_peak_day_200
```

Run the full day as timed waves instead of one uninterrupted burst:

```bash
./.venv/bin/python -m testing.run_live_order_day_profile --pay --run-schedule --schedule-scale 0.02 --per-order-delay-seconds 0.5 sandbox_peak_day_200
```

Create and pay the full profile in Sandbox:

```bash
./.venv/bin/python -m testing.run_live_order_day_profile --pay sandbox_peak_day_200
```

### Export a real order into a fixture

```bash
./.venv/bin/python -m testing.export_order_fixture ORDER_ID fixture_name
```

That writes:

- `testing/fixtures/orders/fixture_name.json`

The export format matches the summarized output from
`scripts.inspect_order`.
