# Auto Trader V2 Phase 2 — Read-only account and market adapters

Date: November 20, 2026
Existing feature branch: feature/auto-trader-v2
Application version v1.3.1; V2 core 2.0.0-alpha.2.

## Implemented
- app/trader_v2/readonly_adapters.py: one source-specific read-only account observation for Schwab, Webull, Robinhood Crypto and Paper. It reads bounded private worker snapshots and never calls broker SDKs, refreshes credentials or submits orders. Missing, stale, rotated or inconsistent evidence fails closed.
- app/trader_v2/market_sources.py: validated source-specific Schwab quote cache, direct Webull OpenAPI quote payload, signed Robinhood bid/ask and Coinbase public WebSocket cache parsers, plus timestamped completed paper replay candles. No timestamps, bids/asks, last trades or session authorization are fabricated.
- app/trader_v2/cached_provider.py: V2 MarketDataProvider-compatible read-only cache bridge. Schwab signed quote source and Coinbase public crypto signal source use their existing files. The provider can read explicitly configured closed-candle CSV replay and cannot claim executable market session.
- Authenticated GET /api/v2/status and existing Trading operations card now show four account readiness observations and market source coverage. It does not expose full account references, API keys or new order controls.

## Tests
- Synthetic broker adapter tests cover fresh/stale/expired worker observations, credential changes, wrong selected Webull account, Schwab supervisor state, missing/malformed balance fields, crypto buying power versus equity, private file permissions and nonexistent data.
- Synthetic market tests cover verified timestamp provenance, crossed quotes, missing last trade, stale data, missing venue time, paper completed 1m replay bars, and separate cached MarketDataProvider protocol.
- Existing V1 Python tests and all JavaScript UI tests must pass. CI validates and publishes an immutable v2-foundation image on the existing branch.

## Incomplete and explicitly excluded
- No V2 broker API write access, live execution, automated signal-to-broker cutover, second background worker, or reset of legacy trading journals.
- This work reuses recent V1 worker snapshots. Direct per-broker network and OAuth/403/429 probes remain a later Phase 2 task, and provider health is NOT proof that a broker can accept an order.
- Schwab invalid_grant requires broker reauthorization; it is never inferred from presence of a token file.
- Webull quote entitlement probes do not supply a fully executable cached bid/ask. Robinhood Coinbase mid is external signal data, not signed broker execution price.
- Shared AI, deep historical replay, portfolio cost basis and all four V2 account templates remain later milestones.

## Required production evidence
Immutable image, snapshot/config backup, healthy original TrueNAS app, signed-in V2 status endpoint and 4 adapter observations with correct null coverage, unchanged V1 Webull/Robinhood permissions and Schwab journal. No synthetic fills reported as broker fills.
