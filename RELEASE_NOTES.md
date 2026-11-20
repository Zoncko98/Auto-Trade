## v1.3.1 — V2 Phase 2 read-only data adapters

The shared V2 core now has read-only broker/account observations for the existing Schwab, Webull, Robinhood and Paper accounts, source-specific quotes, and a cached data provider. The existing Trading operations panel displays freshness, broker permission and account-value coverage without inventing missing numbers.

V2 engine 2.0.0-alpha.2 remains disabled by default and has no live-order write API. It does not start a second live worker or alter existing risk limits. Full source-specific live SDK probes, shared AI, historical profitability replay and live broker cutover remain outstanding.

## v1.3.0 — V2 experimental foundation, V1 remains the production trading engine

V2 2.0.0-alpha.1 introduces canonical shared trading models, transactional order events, separate stock/crypto strategy controllers and simulated-only execution. This is the first milestone of the V2 architecture and does NOT constitute a live-trading cutover.

The new collapsed V2 foundation panel in existing Trading operations reads an authenticated GET status endpoint. The V2 feature flag defaults off; AUTO_TRADER_V2_LIVE cannot enable live brokerage orders in this release. Legacy V1 live brokers and account permissions remain the same.

Outstanding: source-specific market feeds and live adapters, shared AI policy service, historical replay analytics, identical V2 account pages, full shadow comparison and account-by-account live cutover. No new live broker fills or V2 trading profitability are claimed.

## v1.2.5 — Restore monitoring after safe worker errors

Schwab no longer remains inactive forever after an ordinary pre-order data failure. When no previous order is ambiguous, the worker keeps monitoring and a crashed subprocess can restart with bounded backoff, re-running all broker and order checks. Unresolved or replaced orders, halted journals, missing history and repeated failures continue to block autonomous recovery.

Webull and Robinhood permissions and strategies are unchanged. Webull is disarmed in the latest production state; no source update automatically authorizes live trading. Robinhood continues scanning and declines entries that lack qualified signals. Paper AI/news settings are unchanged pending a controlled comparison.

## v1.2.4 — Schwab owner risk controls

Schwab's Risk & Start tab now allows the owner to set strategy capital and all eight existing live risk controls. The old fixed $25/$100/three-position internal clamps no longer override the saved account-specific policy. New orders remain bounded by verified spendable cash, account equity, remaining allocated strategy capital, signal approval and all broker and journal safeguards. Increasing risk settings can cause larger losses or more orders; it does not guarantee more opportunities.

An in-place migration supplies a $100 strategy capital default for prior eight-field records without altering their stored revision. No live test orders are placed as part of release validation.

## v1.2.3 — Schwab worker and portfolio heartbeat recovery

A temporary missing or stale completed stock candle no longer terminates Schwab monitoring; all broker orders remain blocked during that incomplete-data cycle. While order permission is paused, the worker refreshes read-only Schwab account holdings and valuation every 60 seconds. The supervisor still refuses automatic restarts after other live-order worker failures.

This release must be deployed with live Schwab order submission deliberately paused; users reauthorize live orders in the UI after successful monitoring and reconciliation verification. No real-money test orders are part of the acceptance test.

## v1.2.2 — Broker worker recovery (2026-11-19)

This release addresses Webull SDK rate limits in dashboard control requests and Robinhood history overrun above 50 pages. Operator authorization never bypasses per-order broker checks. Broker order-history outages leave the Robinhood scanner online in a degraded state while order submissions remain blocked. The release itself does not establish any Webull broker fills or Robinhood profitability.

## v1.2.1 — Mobile workstation and Robinhood valuation (source candidate, 2026-11-19)

This release simplifies the existing Schwab, Robinhood, Webull and Paper trading workspaces for narrow and portrait touch screens, with account selection and primary tabs always available. It also distinguishes genuinely unavailable Robinhood quote data from zero and supports a timestamp-checked external indicative USDC price when the broker does not offer one. External price marks are display-only and never authorize orders or substitute for broker execution checks. P/L is never invented when purchase history is missing.

Verification: Python and JavaScript test suites plus real-device-dimension browser rendering. A successful source build or installed container does not establish broker-side fills or profitability.

# Releases

> **Source milestone (November 5, 2026):** `main` declares **v1.2.0**. This is the checked-in source version, **not** a verified running TrueNAS version or an immutable tagged release. The existing deployment may continue to display v1.1.10 until intentionally rebuilt and updated. GitHub branch pushes publish candidate images; an explicit `v*` tag publishes `:stable`. A stable tag and production upgrade were intentionally **not** performed by this documentation change.

## v1.2.0 — Multi-broker workspaces, risk controls and performance diagnostics

- Unifies the layout of the four **existing** Schwab, Robinhood Crypto, Webull and Paper Trading workspaces without adding a new dashboard.
- Adds guarded Robinhood Crypto and Webull broker/account experiences with independent authorization, market-data checks, position visibility, journal reconciliation and operational evidence. Broker acceptance and fills are not certified by the source release.
- Adds Robinhood trade performance Excel exports and fee-aware entry/exit *shadow* diagnostics that do not modify live trade rules.
- Includes optional-news handling, independently mirrored Webull five-minute stock evaluation, AI/connection status consolidation and automated regression coverage.
- See [CHANGELOG.md](CHANGELOG.md) for the detailed changes and [README.md](README.md) for privacy-redacted screenshots of the existing deployed UI.

**Release boundary:** no automatic stable promotion, TrueNAS upgrade, simulated brokerage fill or live broker order is implied by the v1.2.0 source version. Cash and paper accounts remain separately authorized.

## Historical release context

Versions before v1.1.7 were deprecated due to incomplete paper-trading operation; their tags remain for inspection. v1.1.7 introduced repaired experimental paper feeds. v1.1.9 and v1.1.10 subsequently addressed the shared account worker and paper AI routing. None of these historical versions certify profitability or live brokerage fills.

## v1.0.0 — Forecast-enabled Auto Trader

Captured from the working TrueNAS + AI workstation deployment, including five-candidate read-only next-session research, Chronos-Bolt, FinBERT, LightGBM with holdout validation, and Ollama model selection.

**Important:** This is an archival snapshot. Its deployment files contain machine-specific LAN addresses and filesystem paths. Use the portable installer development branch for new systems, not the archival compose files.

The LightGBM model did not beat the no-change baseline in its initial test. Forecasts remain research only and never authorize orders.

## v0.9.0-beta — Frontend v2 (previous build)

Historical build before next-session forecast integration.
