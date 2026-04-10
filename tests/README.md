# Tests

## Directory Structure

```
tests/
├── conftest.py                        # Global pytest config, Fubon credential skip helpers
├── unit/                              # Fast, mocked, no external deps
│   ├── test_fubon_account_unit.py
│   ├── test_fubon_realtime_unit.py
│   ├── test_fugle_realtime_unit.py
│   ├── test_masterlink_realtime_unit.py
│   ├── test_sinopac_realtime_unit.py
│   ├── test_order_executor_unit.py
│   ├── test_position_utilities.py
│   ├── test_calculate_price_with_extra_bid.py
│   ├── test_realtime_provider_features.py
│   └── test_realtime_tick_pct_change.py
├── integration/                       # Requires real API credentials
│   ├── test_fubon_account_integration.py
│   ├── test_real_order_accounts.py
│   ├── test_schwab_account.py
│   ├── test_position_from_report.py
│   └── real_order_helpers.py
├── fixtures/                          # Test data and mock objects
│   ├── fubon_sdk_responses.py
│   ├── fubon_test_data.py
│   └── fubon_mocks.py
└── utils/                             # Test utilities
    ├── test_base.py
    └── mock_helpers.py
```

## Running Tests

### Unit tests (recommended starting point)

```bash
pytest tests/unit/ -v
```

### Integration tests (requires broker credentials)

```bash
pytest tests/integration/ -v -s
```

### Run a specific test file or method

```bash
pytest tests/unit/test_order_executor_unit.py -v
pytest tests/integration/test_fubon_account_integration.py::TestFubonAccountIntegration::test_get_cash -v -s
```

### Filter by keyword

```bash
pytest tests/ -k "price" -v
```

## Fubon Integration Tests

These tests connect to real Fubon APIs. Set the following env vars:

```bash
export FUBON_NATIONAL_ID="..."
export FUBON_ACCOUNT_PASS="..."
export FUBON_CERT_PATH="/path/to/cert.pfx"
# Optional:
export FUBON_CERT_PASS="..."
export FUBON_ACCOUNT="..."
```

Tests are automatically skipped when credentials are missing.

## Safety Notes

- Integration tests use real broker APIs and may create orders (designed with low prices to avoid fills).
- Orders are automatically cancelled in test teardown.
- Run integration tests in a test account or with minimal funds.
