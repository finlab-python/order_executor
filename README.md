# finlab.online

Multi-broker order execution framework for automated portfolio rebalancing. Part of the [FinLab](https://doc.finlab.tw/) quantitative trading package.

## Supported Brokers

| Broker | Module | Realtime |
|--------|--------|----------|
| Fugle | `brokers.fugle` | Yes |
| Sinopac (Shioaji) | `brokers.sinopac` | Yes |
| Fubon | `brokers.fubon` | Yes |
| Masterlink | `brokers.masterlink` | Yes |
| Schwab | `brokers.schwab` | No |
| Binance | `brokers.binance` | No |
| Pocket | `brokers.pocket` | No |
| E.SUN | `brokers.esun` | Yes (via Fugle) |

## Package Structure

```
finlab/online/
├── core/               # Abstract interfaces, position, executor, enums, realtime
├── brokers/            # Broker-specific Account implementations
├── dashboard.py        # Cloud-connected multi-strategy rebalancing engine
├── panel.py            # Jupyter notebook GUI for interactive order placement
└── tests/              # Unit and integration tests
```

## Usage

```python
from finlab.online import OrderExecutor, Position

# See https://doc.finlab.tw/details/order_api/ for full documentation.
```

## Testing

```bash
# Unit tests (fast, mocked)
pytest tests/unit/ -v

# Integration tests (requires broker credentials)
pytest tests/integration/ -v -s
```

See [tests/README.md](tests/README.md) for credential setup and details.

## Contributing

Contributions are welcome. All changes must pass the existing test suite.
