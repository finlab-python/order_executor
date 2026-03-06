# Realtime Future Work

## Current Status
- Core `RealtimeProvider` now exposes `Tick`, `Trade`, `BidAsk(Top5)`, `OrderUpdate`, `Fill`, and polling-based `BalanceUpdate`.
- Taiwan broker adapters in this repository now cover:
  - `Sinopac`: `Tick + BidAsk + OrderUpdate + Fill + BalanceUpdate`
  - `Fubon`: `Tick + BidAsk + OrderUpdate + Fill + BalanceUpdate`
  - `Masterlink`: `Tick + Trade + BidAsk + OrderUpdate + Fill + BalanceUpdate`
  - `Fugle`: `OrderUpdate + Fill + BalanceUpdate`
- Unit coverage exists for core realtime helpers plus broker callback bridges for `Masterlink`, `Fubon`, and `Sinopac`.

## 1. Broker Coverage Expansion
- Add full `Tick + Trade + BidAsk(Top5) + OrderUpdate + Fill + BalanceUpdate` adapters for brokers that currently expose only order callbacks (`Fugle/ESUN` today has no stock websocket market-data adapter in this repository).
- Evaluate adding crypto/US brokers to `RealtimeProvider` with the same event contracts and unit tests.

## 2. Push-Based Balance Updates
- Replace polling-based `subscribe_balances()` with broker-native push callbacks when SDKs expose them.
- Keep polling as fallback for unsupported accounts and non-trading hours.

## 3. Order/Fill Schema Hardening
- Build fixture-driven parser tests from real callback payload captures (ACK/MAT/error/cancel/reject) for Sinopac, Fubon, Masterlink.
- Finalize per-broker quantity unit conversion rules (shares vs lots) for all market types (`Common`, `IntradayOdd`, `Odd`, `Emg`).

## 4. Reconnect & Resubscribe Strategy
- Add standardized reconnect policy in `RealtimeProvider`:
  - connection state transitions,
  - exponential backoff,
  - automatic re-subscription (`trades`, `aggregates`, `books`),
  - callback idempotency guarantees.

## 5. Observability
- Add structured logging hooks for all realtime events with broker/source tags.
- Add metrics counters for dropped messages, callback exceptions, reconnect attempts, and balance poll failures.

## 6. Backward Compatibility
- Publish migration notes for downstream users moving from `on_tick/on_bidask` only to `on_trade/on_balance`.
- Keep old callback APIs stable while introducing richer dataclasses and helper properties.
