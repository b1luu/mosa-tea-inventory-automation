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

### Export a real order into a fixture

```bash
./.venv/bin/python -m testing.export_order_fixture ORDER_ID fixture_name
```

That writes:

- `testing/fixtures/orders/fixture_name.json`

The export format matches the summarized output from
`scripts.inspect_order`.
