# Auto Trader V2 Phase 1 — Implementation and acceptance record
Baseline: 29201178e28a (v1.2.5)
Branch: feature/auto-trader-v2
Application version: v1.3.0; V2 engine version: 2.0.0-alpha.1

## Phase 1 architecture
- models.py: typed Account, Capability, MarketSnapshot, Candle, Candidate, AIReview, RiskPolicy, RiskDecision, OrderIntent. Money uses Decimal, dates timezone-aware.
- contracts.py: canonical TradingBroker, MarketDataProvider, StrategyController and AIReviewer protocols. Only the simulated broker implements the V2 writable broker contract in this phase.
- strategies.py: versioned, deterministic closed-candle stock and crypto SMA reference controllers. Not validated profitability strategies.
- risk.py: broker permission and account selection, quote staleness, spread, market session, non-borrowed cash, exposure and position concentration, entry/daily-loss caps, separate exit cap.
- store.py: separate WAL SQLite store with synchronous FULL fsync, append-only event log, idempotency fingerprint, allowed transitions and unresolved-order states.
- simulation.py: persistent simulated cash and holdings, fees, slippage, idempotent broker receipts and reconciliation by original key. NO real broker network calls.
- engine.py: one shared signal → optional AI assessment → risk → durable intent → simulated execution → reconciliation pipeline. Unknown POST never retransmits an order.
- demo.py: opt-in synthetic virtual-order example with a stable signal identity across restarts.
- status.py and /api/v2/status: authenticated, read-only status. Feature flag disabled by default; live broker order authority is always false.

## Run a synthetic test
From the repository with its Python dependencies:
  AUTO_TRADER_V2_ENABLED=true PYTHONPATH=app python3 -m trader_v2.demo --state-dir /tmp/auto-trader-v2-fixture
Run twice and confirm one persisted intent and unchanged virtual cash after the second run.

## State boundaries
V2 state lives under its own v2/events.sqlite3 and v2/simulation.sqlite3 namespace with owner-only permissions. No V1 state is migrated or overwritten. V2 has no installed live Schwab, Robinhood or Webull adapter, no live submit endpoint, no recurring V2 worker, and no right to turn on any account. AUTO_TRADER_V2_LIVE=true does NOT grant this authority.

## Milestone-one acceptance
Full Python and JavaScript regression suites; 32 synthetic V2 tests for domain, WAL/concurrency, duplicate key, crash-after-fill reconciliation, stale quote, disarmed account, AI veto, and exit priorities; authenticated dashboard route/asset checks and a reproducible no-network paper demo. A passing build is not proof of V2 broker execution.

## Next development
Phase 2 read-only market-data normalization and real broker capability adapters.
Phase 3 shared AI service with typed response/TTL/cache and two versioned controllers.
Phase 4 live order orchestration only after reconciliation and shadow agreement.
Phase 5 identical four-account UI; Phase 6 replay, cutover and broker-accepted/fill verification.
