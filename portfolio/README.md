# Portfolio Sync Architecture

Keeps a finlab `Portfolio` (which stays in finlab) in sync with a broker account.
finlab's old `finlab.portfolio.<module>` paths load these modules.

Public API: `PortfolioSyncManager` lives in `portfolio_sync_manager.py`.

Open this file when you need:
- `portfolio_sync_manager.py`: the public facade and compatibility surface
- `sync_storage.py`: local/path/cloud persistence and typed payload conversion
- `sync_state.py`: position lookup, history resolution, and combined-position assembly
- `sync_execution.py`: `OrderExecutor` creation and `sync()` flows
- `sync_market_data.py`: market snapshots and position-value helpers
- `sync_reporting.py`: total-position DataFrame building and `__repr__` formatting
- `sync_update.py`: update orchestration, fund planning, and strategy rebuild flow
- `sync_decisions.py`: decide which strategies must be updated
- `sync_stops.py`: stop-loss / take-profit trigger handling
- `sync_margin.py`: cash/margin reconciliation
- `sync_display.py`: shared display DataFrame builders
- `sync_validation.py`, `validation.py`: pure validation and computation helpers
- `broker_history.py`: broker fills, holdings and cash behind finlab's `TradeReview.from_account()`

Dependency direction:
- pure helpers: `sync_validation`, `validation`, `sync_decisions`, `sync_stops`, `sync_margin`, `sync_display`
- runtime helpers: `sync_storage`, `sync_state`, `sync_execution`, `sync_market_data`, `sync_reporting`, `sync_update`
- `portfolio_sync_manager.py` depends on helpers and should stay as the facade

Rules:
- `portfolio_sync_manager.py` is the public wrapper, not the implementation dump
- storage/state/execution/reporting helpers should not import `PortfolioSyncManager`
- new sync logic should get one canonical home instead of landing back in the manager
