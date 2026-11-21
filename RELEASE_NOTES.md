## v1.3.13 — V2 broker migration preflight

V2 now displays authenticated, read-only cutover readiness for Schwab, Webull, Robinhood Crypto and Paper in the existing Trading Operations panel. A connected broker is not V2-live-ready: order journal reconciliation, market-executable quotes, correctly mapped account-specific limits, working adapters, and explicit V1-to-V2 writer handoff must all be independently verified. Saved V1 limits are shown as source evidence, not newly granted V2 order permission. No live V2 orders were placed.

Production preflight: Schwab connected/worker online, local V1 journal 19 terminal orders and no unresolved local entries, Webull/Robinhood V1 adapters connected; current V1 workers still own each live account. The obsolete separate trading-live container targeting the same Schwab account was stopped safely, without deleting its credentials or history. V2 stock market-source freshness and full broker order reconciliation remain outstanding. V2 core 2.0.0-alpha.9 is read-only for live broker migration.

## v1.3.12 — Schwab setup moved into Broker Connections

The navigation sidebar always shows Broker Connections just below Account Overview. Schwab now has an inline setup card with one Connect / Reconnect Schwab action, official sign-in link, account verification and optional real-money enablement, like the other connected brokers. Developer credentials and exact registered callback are advanced settings, and the callback paste form is shown only when the Schwab developer callback still uses the loopback address.

Saved and revoked tokens no longer force the operator to select the correct type of authorization or clean up old private backups manually. The current OAuth session is reused across page reloads, with an explicit new sign-in option when necessary. Tokens remain protected until replacement has passed broker account validation. No live order permissions or safeguards were automatically modified.

The live Schwab worker may remain offline until official user-driven OAuth sign-in is completed. V2 alpha.8 remains paper-only.

## v1.3.11 — Schwab Start Trading and OAuth reconnect clarity

The Schwab workspace now distinguishes Start trading from Reconnect Schwab rather than sending Start to generic Broker Connections. The live API confirms a revoked authorization and the real-money permission endpoint refuses to start until Schwab's OAuth consent and worker verification succeed. The dedicated reconnect action opens the registered Schwab flow.

Production preflight on Nov 21 confirmed REAUTH_REQUIRED, worker offline, order permission paused, and no order journal halt. This release does not bypass broker authentication, change trading risk parameters, or place broker orders. V2 alpha.8 remains independent and paper-only.

## v1.3.10 — V2 measurable paper scan outcomes

The existing Trading Operations V2 panel adds independent BTC/ETH paper scan coverage and economic scorecards. Each shows actual observed/no-signal minutes, actual simulated fills if any, model shadow PASS/VETO/UNAVAILABLE counts, virtual-account marked P/L and paper drawdown. No fills means no measured trading profitability; the virtual account remains distinct from each live broker.

Read-only production evidence before this release showed both BTC and ETH accumulating real closed candles but each at NO_SIGNAL and zero simulated orders. A separate actual configured Ollama test timed out after six seconds, despite healthy model endpoint discovery. This release reports model inference timeouts accurately but does not automatically switch models or weaken gates. V2 alpha.8 remains non-live and user permission settings are unchanged.

## v1.3.9 — V2 Ollama shadow decisions alongside safe paper execution

When the public crypto paper controller identifies a qualified signal, V2 may request a bounded JSON PASS/VETO review from the existing configured Ollama model and store it next to the simulated baseline outcome. The review has NO authority over risk, entry sizing or order submission and may report UNAVAILABLE when the local model is slow or offline. Without an operator-configured model it reports NOT_CONFIGURED. A no-signal scan reports NOT_INVOKED. The independent V2 paper worker and all V1 brokers retain their prior permissions.

The deployed V2 core is 2.0.0-alpha.7. This is shadow AI integration, NOT validated AI-controlled broker execution or performance.

## v1.3.8 — Fresh BTC/ETH public-feed V2 paper worker; no broker orders

V2 now independently acquires timestamped Coinbase Exchange public ticker data, builds real completed minute bars, and continuously supervises simulated BTC and ETH paper strategy scans when the existing Paper Trading setting is on. The workflow is an actual shared V2 CryptoController -> deterministic risk -> durable intent/EventStore -> SimulatedBroker path, with separate virtual balances, fees and order status in existing Trading Operations.

This is a broker-free, no-AI baseline. Real Robinhood/Webull executable bid/ask and live fills are NOT inferred from Coinbase; public data may be stale and the worker remains WARMING_UP until a complete sequence of real closed bars exists. Schwab's revoked OAuth credential and V2 live writer cutover remain separate blockers. V2 core is 2.0.0-alpha.6.

## v1.3.7 — On-demand historical paper replay through the actual V2 simulated pipeline

The authenticated V2 Trading Operations panel now supports selecting previously recorded closed paper-market candles and running an explicit historical synthetic replay with its own permanent event journal and report. This needs no live broker authentication and can never write a live brokerage order. The report distinguishes strategy signals, blocked decisions, simulated fills, assumed transaction costs and net simulated P/L.

This is an operator-triggered *historical* paper/replay baseline, NOT a continuously scanning fresh-market paper worker or broker-verified trading. The general V2 feature flag and all V2 live-order authority remain disabled. Schwab still requires authorized OAuth reauthentication; Webull and Robinhood V1 operation is unchanged. V2 engine is 2.0.0-alpha.5.

## v1.3.6 — Explain unknown and blocked V2 trading gates without inventing signals

The existing authenticated Trading operations panel now displays one read-only diagnostic explanation per Schwab, Webull, Robinhood Crypto and Paper account, including the first known blocker, next action and unverified signal/AI/risk/order gates. V2 version is 2.0.0-alpha.4; paper/shadow libraries are not armed and the original V1 broker execution paths remain unchanged.

No new live broker authority is enabled. This is readiness transparency, not verified live broker trading or completed four-dashboard unification. See CHANGELOG.md for regression coverage and limitations.

## v1.3.5 — Unified-image regression portability fix

Portability update for a source/UI regression that located web/index.html incorrectly inside the built Docker image. No application runtime logic or broker permissions change from v1.3.4. The release retains the verified Schwab OAuth REAUTH_REQUIRED state and separated entry/exit caps.

## v1.3.4 — Schwab reauthorization status persistence fix

Validated the persistent REAUTH_REQUIRED marker on TrueNAS's existing 0755 live-state directory while requiring 0600 marker files and refusing writable parent directories. This fixes the production-detected failure to suppress repeat OAuth refresh attempts after a revoked Schwab grant. Prior v1.3.3 Schwab exit-priority and UI changes remain included.

No broker credentials are changed and V2 has no live-order authority. See CHANGELOG.md for exact scope and regression evidence.

## v1.3.3 — Schwab exit-order priority and revocation-aware worker recovery

Legacy Schwab automation now evaluates risk-reducing exits before its entry-side daily order ceiling, while enforcing an independent user-configurable daily exit-order allowance. Existing saved entry, cash, exposure and loss limits are preserved. The authenticated Schwab Risk & Start form shows both limits and the next-order preview.

When the Schwab refresh token is rejected, the worker writes a nonsecret REAUTH_REQUIRED marker. Its supervisor stops repeated authentication attempts against the same token, and V2 diagnostics show a reconnect action rather than falsely asserting the account is online. No token is rotated or OAuth login performed automatically.

The V2 shared AI/replay foundation remains paper-only and is not the live execution engine. This release does not assert broker-accepted or broker-filled production orders. See CHANGELOG.md for regression coverage and remaining V2 cutover work.

## v1.3.2 — V2 Phase 3 advisory AI and synthetic replay libraries

This release adds an isolated V2 shared AI reviewer and Ollama JSON transport. Model decisions are strictly typed, short-lived, symbol-bound and advisory; mandatory AI failures block entry. None of these components can submit live broker orders, and no V2 live adapter or account cutover is enabled.

A historical synthetic candle replay facility runs stock/crypto controllers through the same V2 deterministic risk, order intent and simulated brokerage path. Reports include after-simulated-cost equity, blocked decisions, and a gross buy-and-hold reference. Historical OHLC closes are **not executable broker quotes**; replay profitability is not certified. The simulated broker now supports an explicit historical clock and bounded crypto accounting precision.

V2 API status identifies the Phase 3 libraries as available but not runtime-connected. V2 feature flag defaults to off; Schwab, Robinhood and Webull V1 workers retain existing account permissions, journals and order safeguards. See CHANGELOG.md for detailed tests and pending integration milestones.

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
