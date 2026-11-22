## v1.3.53 ? Crypto funding/session proof without stock-market assumptions

The V2 Robinhood Crypto migration preflight now models Robinhood's authenticated USD buying power and API-tradable 24/7 crypto product capability as distinct signed evidence. It never calls that balance stock settled cash, assumes open maintenance windows, or relaxes the separately verified broker spread and quote freshness. Schwab and Webull stock cash/session requirements are unchanged.

This fixes two incorrectly permanent V2 crypto cutover blockers. The existing V1 brokers retain exclusive trading authority while independent quote, risk, parity, order acceptance and replacement-worker handoff checks remain outstanding.

## v1.3.52 ? V2 account execution coordinator and admission telemetry

The same original TrueNAS app now supervises a dedicated, single-instance V2 execution coordinator. Account-specific V2 execution is blocked until signed brokerage data, validated V1 strategy/exit policy parity, inherited history, an exclusive V2 ownership record and an independent short-lived broker handoff have all passed. The new process has no default privileged broker factory and cannot mint permission from a dashboard checkbox or a worker heartbeat.

The existing four broker/paper dashboards remain in place. Authenticated Trading Operations distinguishes the live coordinator's registered health from actual trading authority, and shows redacted per-broker blocker codes. V1 accounts remain the only order writers until accepted staged cutovers; no V2 fills or broker live acceptance are claimed by this release.

## v1.3.51 ? Robinhood stale GTC bot-entry reconciliation

An old open original Auto Trader buy can block all autonomous orders. This release provides account-configurable (default two-hour) automatic cancellation only of an independently confirmed, entirely unfilled, original bot-created Robinhood GTC buy, under the existing authorized account's writer lock. The attempted broker cancellation is journaled exactly once before the request. A canceled state is shown only when later confirmed by Robinhood. Partial fills, missing broker proof and uncertain network requests remain blocked, and no new buy or sell orders are submitted by this feature.

The Robinhood account Risk settings include a 0-minute OFF option and expose current cancellation/reconciliation state. Other V1 brokers and all V2 ownership gates remain unchanged. TrueNAS app updates in place with original rollback and preserved journals.

## v1.3.50 ? V1 worker lifecycle observes exclusive V2 ownership

The existing TrueNAS supervisor now checks the durable account-specific V1/V2 ownership record before launching or restarting Schwab, Webull or Robinhood's original execution workers. This closes a restart race in the eventual V2 account handoff. Mixed-account Webull processing remains restricted by the already-existing per-account POST lock. Unknown account ownership fails closed.

The authenticated Trading Operations view shows source-validated V1 writer placement for each broker. This is a prerequisite for cutover, not proof that any V2 order writer has been authorized or that a broker accepted a trade. No V1-to-V2 transfer or change of current user trading restrictions is made by this release.

## v1.3.49 - Robinhood legacy V1 order history compatibility

V2 now counts older Robinhood broker-confirmed fills and terminal order resolutions conservatively when the original V1 journal lacks a local created_at timestamp. This preserves daily risk and symbol reentry cooldown limits without manufacturing timestamps or modifying any original order. Remaining unverified records still fail closed and appear as redacted diagnostic codes in the authenticated V2 Operations view.

The existing V1 account writer remains authoritative. No live V2 order submission or writer cutover was performed. The in-place TrueNAS release retains its full rollback snapshot and existing account settings.

## v1.3.48 - Safe original-order identity, V1 managed inventory and local AI latency

The V2 executor prevents the same broker-confirmed managed holding from generating a second live SELL order merely because a new market quote arrived. A quote remains mandatory for validation; order identity instead binds to the original signed position lot so duplicate scans reconcile one existing order across worker restarts. V2 now has read-only source-backed managed-lot and per-account exit-policy loaders for Robinhood and Webull. Schwab historical cost basis remains unverified, so automatic V2 adoption is blocked.

The existing Ollama model qwen3.5:4b was independently reached on TrueNAS. It completed a strictly typed V2 mock candidate review; configured timeout bounds now allow normal responses while continuing to reject stale quote prices after model latency. This does not imply positive trading performance or production broker acceptance.

Current V1 order writers remain the sole authorized brokerage writers. No live V2 orders were submitted, no broker was automatically armed, and all pending user/broker acceptance requirements stay blocked. Deployment updates the existing TrueNAS application in place with a retained pre-update Compose backup and ZFS snapshot.

## v1.3.47 - V1 daily risk inheritance for V2 account cutover

V2 preserves the selected original broker account's historical order counts, pending-order safety, daily exit limit, specific Robinhood reentry cooldown and Schwab's separate total-day new-entry ceiling without starving independently authorized protective exits. A fresh signed broker account and fully reconciled V1 order-history preflight are required before any inherited count is accepted. Unknown data does not default to zero.

Authenticated Trading Operations shows whether V1 trade-day limitations were inherited alongside existing read-only signed migration gates. All broker order-writing remains under V1 by default. The V2 production execution worker is still awaiting full per-account strategy/exit parity, market/funding acceptance and a single-writer transfer, and there have been no live V2 orders.

## v1.3.46 - V2 broker-specific exits, historical parity and read-only broker observation

The V2 shared scanner now evaluates separately verified managed-lot cost basis, broker available quantity, account-specific stop, target, trailing and holding-time rules before issuing a SELL or considering another BUY with existing bot holdings. A generic bearish cross is not alone sufficient to liquidate a position. Robinhood per-order protective exit sizing remains bound to its saved max_order_usd; V2 live stock continuation can use the same moderate completed-bar signal as V1 Schwab and Webull.

The Webull signed preflight may independently verify selected account stock permissions and a timestamped read-only signed stock market quote. It cannot establish settlement, broker order acceptance, exclusive V1-to-V2 writer handoff or full V1 strategy parity, so all such launch gates remain blocked until externally verified.

This release does NOT arm any broker, transfer an account order writer, or submit live V2 brokerage orders. The existing TrueNAS application, V1 account permission/worker operation, original order journals and rollback path are preserved.

## v1.3.45 ? Protective sell reliability in V2 execution coordinator

V2 no longer evaluates an entry-only AI requirement before classifying protective SELL signals. This resolves a potential failure to manage validated holdings when the AI entry model is unavailable or disabled. BUY orders still require the account's validated AI policy and model. Existing per-account broker sessions, risk and order-reconciliation safeguards are unchanged.

This update does not enable live V2 trading or hand over any V1 broker account. Production cutover still requires a broker-authenticated current session/funds/quote, complete V1 strategy parity, a mutually exclusive writer handoff, and signed broker order verification.

## v1.3.44 ? Account-scoped V2 migration supervisor, read-only standby

The existing TrueNAS Auto Trader supervisor now starts and monitors a V2 account migration observer (no brokerage credentials, no ability to submit or cancel broker orders). The worker continuously reports all three broker's signed prerequisites and V1 telemetry while keeping V1 account order writers authoritative. Trading Operations explicitly differentiates a healthy V2 standby coordinator from a live execution worker.

This is migration infrastructure only: no V1/V2 writer handoff, new order, revised risk limit, trading-mode arm, or broker configuration change is made by this release. Future V2 order execution remains blocked until broker-specific funding/session/order proof, strategy-exit parity, and an exclusive account-scoped authorized transfer are verified.

## v1.3.43 ? Signed Schwab V2 migration evidence

The active Schwab V1 worker now periodically observes authenticated account and order data using its existing signed client, then emits a private, redacted Schwab V2 migration preflight. It records current market-session and funding evidence only when independently established. Trading Operations lists Schwab beside Robinhood and Webull for the same fifteen launch acceptance gates.

No V2 live account handoff has occurred. V1 remains the only broker writer and this release does not modify account risk settings, tokens, broker authorization, or journals. A closed stock market and any unverified settled cash continue to block Schwab V2 cutover. The existing TrueNAS app is updated in place with rollback preserved.

## v1.3.42 - Webull signed preflight freshness across deployment

After upgrading, the supervised Webull migration preflight now rejects a report produced by earlier funding-validation rules, even if the report is younger than 20 minutes. The read-only signed GET check can then refresh evidence immediately. No old report can authorize an account and the V2 live broker writer remains unarmed. This is a same-app TrueNAS update, retaining all existing trading state and broker permissions.

## v1.3.41 - Webull settled funding and migration evidence

A signed Webull USD cash record containing explicit settled-cash and reserve/holdback fields now yields a conservative read-only funding verification. Missing entries or contradictory totals never become synthetic cash. The V2 Webull live adapter caps potential buys to this budget. Trading Operations reports verified holdings and funding separately from live authority.

No V2 broker execution has been enabled. Robinhood still requires a verified executable broker spread/session/funding and single-writer cutover, while Schwab still lacks a signed V2 migration preflight. V1 brokerage execution remains authoritative; no live orders were submitted for this change.

## v1.3.40 - Webull signed portfolio inventory preflight

This release adds a signed GET-only Webull position audit and compares the current broker inventory with broker-confirmed historical bot fills before considering holdings reconciled. Invalid symbols, duplicate/fractional/short holdings and inventory deficits stay blocked. Trading Operations now accurately labels verified read-only order history and does not represent it as live V2 activation.

Robinhood, Webull and Schwab remain on their existing V1 order writers. V2 production cutover is NOT authorized until signed settlement/session conditions, V1 strategy/exit parity, and a single verified account-writer handoff are satisfied. No live V2 orders were submitted as part of this release.

## v1.3.39 — Shared V2 autonomous market-to-order engine

The three signed live adapters now have a common, tested V2 candidate-to-execution cycle. Official closed stock candles and genuine observed Coinbase minute bars produce typed strategies; per-broker signed quotes provide actual order pricing, Ollama reviews entries, and the durable broker journal reconciles original orders. A valid V2 writer lease and verified V1 risk/exit strategy parity are REQUIRED before this code can issue a real order.

The existing TrueNAS application remains the only deployment. V1 orders still own all accounts until live signed account funding, market session, settled orders, V1-inventory adoption and exclusive handoff are independently verified. The release does not mark 3/3 live or activate any V2 production order workers.

## v1.3.38 — V2 stock execution adapters and genuine cumulative order accounting

The same V2 live risk-and-order pipeline now has source implementations for Schwab and Webull stock alongside Robinhood crypto. Account cash, tradability, whole-share pricing, public-vs-broker quote provenance, broker preview, risk caps, and single-account writer locks are enforced. For Schwab the raw broker hash used by V1 remains the exact lock identity, even though V2's journal stores a safe account alias.

A separate read-only projector turns verified broker order receipts into cumulative holdings and fee-adjusted P&L; no receipt and no invented inventory. The existing Trading Operations feature status describes this as source-implemented, not live deployed. Only the existing TrueNAS app is used; V1 workers are unchanged pending a signed cutover.

## v1.3.37 — V2 can safely recover original Robinhood order receipts after restart

The existing TrueNAS app now contains a supervised read-only Robinhood V2 order recovery stage. If a real V2 event journal later contains submitted or uncertain intents, the worker can independently look up their original deterministic client IDs at the broker and reconcile fills/status without posting again. Unknown or unreconciled results remain blocked; never infer a missing order was canceled.

Trading Operations displays this stage. This is necessary plumbing toward a live migration, but no live V2 broker executor, new position exits or V1-to-V2 account transfer has been authorized by this release. Signed funding, market-session and V1 risk/AI/exit parity are still acceptance requirements.

## v1.3.36 — Why live V2 has not launched

Trading Operations now shows the specific signed evidence and execution-worker acceptance gates that must pass before any account changes ownership. It distinguishes broker account/order/quote observations from live authorizations and reports the missing settled-funding, AI/exit, supervisor and exclusive handoff paths instead of displaying a vague 'not ready'.

A successful test build or signed quote still does not start V2 orders. V1 keeps current account ownership; no account permissions, financial records or risk limits have been changed.

## v1.3.35 — Price every Robinhood holding without requiring an unsupported Coinbase pair

The V2 Robinhood account adapter can now value an externally held cryptocurrency using its fresh signed Robinhood bid/ask and timestamp, even when the V2 Coinbase signal feed does not support that asset. Missing or stale broker quotes still block account assessment. This is for accurate gross exposure only, not order permission or new-trade pricing.

Live V2 ownership remains unchanged. Before a live cutover, the account's funding, market session, V1 strategy and exit/risk parity and one-writer handoff still require verification.

## v1.3.34 — Robinhood quote verification uses actual live-source behavior

The V2 preflight no longer fetches slow public trade data *after* obtaining a signed broker quote, which could cause otherwise valid cross-checks to expire. It separately validates broker bid/ask and any broker-reported quote timestamp, with the last trade sourced from a fresh independently timed Coinbase observation. The dashboard shows the exact safe quote validation blockers for supported symbols.

This fixes a preflight reliability defect, not a V2 live-order activation. Broker funding, positions, market-session and single-writer cutover checks remain mandatory.

## v1.3.33 — Account-specific risk inheritance for V2 migration

The Trading Operations migration check now distinguishes saved V1 risk settings that can be safely mapped to V2 from missing or unverified controls. Per-broker cash exposure, daily loss, maximum positions, user allocation and cooldown restrictions cannot silently widen on migration. Structural policy preview does not grant V2 live trading; signed broker account funding/session and ownership transfer remain separate acceptance gates.

## v1.3.32 — Automatic read-only Webull migration-readiness worker

The existing app now schedules authenticated Webull broker preflight observations automatically. Users can still request the same read-only check from Trading Operations, and the dashboard shows the last redacted readiness reason. Broker orders and permissions remain with V1. The new background worker never submits live orders; a full V2 broker cutover still requires signed holdings/funding/market-session evidence and exclusive account ownership.

## v1.3.31 — Fix Robinhood quote-source mismatch before live migration

Robinhood's official signed V2 bid/ask endpoint has no exchange quote timestamp or last trade. V2 no longer requires those nonexistent fields for read-only migration analysis: it independently validates a timestamped Coinbase trade and strict price agreement while retaining the broker's actual signed bid/ask for limit-price risk. A separately labeled quote-source view is available under Trading Operations.

The account-scoped V1-to-V2 ownership-transfer primitive is now durable and independently proof-gated, including generation fencing and guarded rollback. It is **not activated** by this release; there is no V2 live trading worker, no live-order permission, and no broker order POST from V2. Before a real cutover, the supervisor must verify available funding/settlement, broker session, entire holdings, account risk, V1 stop and V2 readiness from signed evidence in the selected account.

## v1.3.30 — Robinhood signed pair limits and one consolidated migration branch

The Robinhood Crypto V2 read-only preflight and adapter now enforce the signed broker's actual increment/minimum/maximum order constraints, rejecting unsupported precision before any possible live order. Robinhood and Webull migration gates remain visible in the existing Trading Operations UI. This is not an activation of live V2 trades.

## v1.3.29 — Run Webull migration checks before enabling live trading

The Webull migration-readiness check can now inspect a previously selected account even while trading is paused. This avoids having to arm real orders merely to diagnose the cutover. Signed history checks are bounded to respect Webull API quotas. An uncertain or incomplete result never grants live trading authority.

## v1.3.28 — Signed Webull order evidence before any live migration

The existing Trading Operations screen now offers **Check Webull migration readiness**, a signed read-only Webull account preflight. This validates independently signed broker account, open orders, balances, positions response and exact historical fill evidence without placing orders. Missing source data, unresolved V1 intents, unsettled cash, incomplete holdings or active V1 writer keep live migration blocked.

The Webull V2 receipt adapter translates broker accepted, partial, terminal fills and cancellations into the shared V2 order schema but refuses to submit any orders. V2 core 2.0.0-alpha.24 remains paper/shadow only. Existing live trading workers and financial history are preserved.

## v1.3.27 — Verify legacy Robinhood fills against signed broker executions

V2 now checks the old Robinhood fill journal against signed broker executions using the original V1 weighted-average execution parser. Tiny fractional quantities and broker-reported execution arrays are treated accurately without guessing costs. Any unverifiable or different fill, price or fee keeps live migration blocked and displays a privacy-preserving reason in Trading Operations.

The existing V1 brokers remain the only authorized live order writers. No real orders are sent by these migrations or tests. V2 core 2.0.0-alpha.23.

## v1.3.26 — Accurate high-precision signed crypto holdings in migration checks

The Robinhood V2 migration probe now accepts valid high-precision signed broker holdings, including small fractional balances, without treating them as bot-owned shares. The live V2 adapter rounds exposure conservatively and still refuses an order when a quote, brokerage position, cost, order ID, fee, or account authorization is not independently verified.

This is an observational broker-data correction, not a live-trading activation. The existing Schwab, Webull and Robinhood V1 order writers remain the only production submitters, protected by the shared account ownership locks. V2 core 2.0.0-alpha.22.

## v1.3.25 — Single-writer protection for broker migration

Every existing Schwab, Webull and Robinhood V1 order-writing path now participates in a protected, cross-process, account-scoped ownership lock. V1 owns each account until an independently verified migration assigns V2; V2 now refuses an account even if a callback claims a handoff unless its persisted owner generation explicitly matches. This prevents both architectures from submitting to the same broker account in the transfer window.

Robinhood's signed read-only migration probe reports sanitized holdings-check failure categories, and the dashboard rejects stale probe evidence. **This milestone does not grant V2 live order authority or pause the existing broker writers**; we will only complete live account cutover after certified broker data and reconciliation pass. V2 core 2.0.0-alpha.21.

## v1.3.24 — Live migration coordination and authenticated broker proof

V2 now has an explicit live-pipeline boundary and an account-locked, idempotent order process for future controlled broker cutovers. Robinhood Crypto has a signed official-API adapter with conservative price, inventory, fee and order-identity validation. The TrueNAS runtime also runs a *read-only* Robinhood migration probe every 15 minutes and surfaces its first verified blocker in Trading Operations.

**No V2 live trading has been armed.** Broker-specific writer handoff, verified market/session conditions and real broker fill acceptance still need to pass before V1 is paused. Existing V1 Schwab, Webull and Robinhood trading processes and account-specific policies remain unchanged. The pre-existing V2 paper simulation continues separately. V2 core 2.0.0-alpha.20.

## v1.3.23 — Broker journal observation and one shared account-section layout

The four **existing** account dashboards now present the same six-section navigation in the same order. Nothing moves to a new dashboard; links continue using the existing broker-specific views and risk controls.

Trading Operations also reads V1 Webull and Robinhood order journals without modifying them. It distinguishes locally stored fills from broker-confirmed executions, flags unresolved/partially terminal intents and missing fill details, and blocks an unsafe V2 cutover. A conservative time-window observation reports when US equities are certainly outside regular hours without ever claiming an authenticated exchange session or broker execution permission.

All three live brokers remain under their existing V1 order writers; V2 remains paper-only/read-only for broker execution. Canonical signed holdings, settled cash, exact market hours, per-broker live adapters and controlled one-writer cutover remain mandatory. New source checks include 735 Python tests (1 skipped) and 22 Node UI files, with no production live-order submissions. V2 core 2.0.0-alpha.19.

## v1.3.22 — Receipt validation before any V2 order is declared filled

The V2 paper executor now checks a broker receipt against the original saved order: broker ID, fill quantity and cumulative progress, BUY/SELL limit price, fees and terminal state must all agree. If any response conflicts, the existing intent is held for reconciliation and is never retried as a fresh order. Partial-fill economics survive cancellation and rejection for later accounting.

This is a contract-hardening milestone for future broker adapters, not a V2 live-trading activation. V1 live brokers and their permissions are unchanged. Latest full local Python regression: 714 tests passed (one skipped). V2 core 2.0.0-alpha.18 still requires market-session/settlement checks, signed broker-order reconciliation and single-writer handoff before any live cutover.

## v1.3.21 — Historical advisory fee/reward evidence retained for V2

The existing authenticated V2 Trading Operations crypto paper 3-hour and 24-hour reports now retain fee-aware shadow classifications for genuine BUY signals. An append-safe migration adds one column to the private scan history and never changes real or simulated order journals. All existing order and risk paths remain exactly as before.

The historical counts represent *advisory counterfactuals*: whether a previously observed price high could hypothetically cover modelled round-trip fees, spread, slippage and a 0.5% net target. They are not broker-executable quotes, proof of future prices, or instructions to trade. This upgrade does not retroactively reclassify older signals. V2 core is 2.0.0-alpha.17.

## v1.3.20 — Cost-aware V2 crypto signal diagnostics, without order changes

V2's live public-market paper scanner now compares a genuine BTC/ETH BUY signal's earlier price resistance to an estimated round trip using its own existing synthetic spread/slippage/fee assumptions. It can flag a signal whose prior observed upside would not pay for execution costs and a 0.5% illustrative net target. This is not a prediction, broker-executable quote, calibrated profitable strategy, or trade permission; the original V2 paper engine and the V1 brokerage live traders remain unchanged.

The existing Trading Operations BTC/ETH paper section displays the diagnostic alongside signal and AI evidence. Every shadow return contains changed_execution=false and live_order_authorized=false. SELL exits are never filtered. V2 core is 2.0.0-alpha.16, and production stock-market session validation and broker-specific live cutover remain outstanding.

## v1.3.19 — Reconciled V2 crypto paper P/L after simulated trading costs

The existing Trading Operations V2 paper section now shows the result of a separate, strict read-only simulator-account reconciliation. It checks that confirmed simulated fills, fees and long position quantities reproduce the account cash and inventory, then reports cumulative realized net simulated P/L and win counts. Any mismatch is explicitly shown as unavailable rather than presenting guessed performance.

Both BTC and ETH simulated accounts currently show three completed buy/sell cycles, zero profitable cycles, assumed fees of $0.06 each, and realized net simulated losses of $0.14 and $0.16 respectively. This is not broker performance. No new V2 orders were placed by this release and V2 live broker write authority remains disabled.

V2 core 2.0.0-alpha.15 still needs independent market sessions, executable quotes, broker lot/cash reconciliation, controlled broker adapters and one-writer cutover.

## v1.3.18 — Confirmed paper activity and why-no-trade evidence

The existing authenticated Trading Operations V2 paper section now shows independent rolling three-hour and 24-hour scan and simulator activity. It distinguishes genuine BTC/ETH candidate signal-minutes from verified simulated fills and displays the actual broker-independent risk blockers: ENTRY_DAILY_COUNT_LIMIT and NO_LONG_HOLDING, without altering the safeguards.

The last three-hour production inspection showed ongoing crypto scans with genuine AI assessments but no new simulator fills. All 12 previously persisted simulated fills occurred before that interval. V2 cannot submit any live broker order. This release makes these differences visible rather than conflating scanner activity with execution.

V2 core 2.0.0-alpha.14 remains read-only for live brokers. This is not evidence of broker acceptance/fills or profitable performance.

## v1.3.17 — Faster local AI shadow evaluation with validated JSON

V2's existing stock and crypto shadow pipelines use the configured local Ollama model with a constrained three-field JSON decision, reasoning-token generation disabled, a bounded token/context budget and the existing six-second timeout. Output still passes the shared AI service's symbol, state, timestamp, schema and expiry checks, and AI has no authority to modify the deterministic risk or order pipeline.

An isolated production synthetic probe succeeded in about 405 milliseconds. This is not proof the next real signal will be timely, and live V2 broker orders are still disabled. Existing Schwab/Webull/Robinhood V1 workers and the current source-faithful V2 risk budget previews remain unchanged.

## v1.3.16 — V2 displays actual per-account V1 risk budget limits without order authority

The read-only V2 live-cutover preflight now distinguishes the user-requested maximum order size from an observed account-specific preliminary permitted new-entry budget. Schwab uses its saved strategy capital, risk percentages, cash/equity and existing market exposure. Webull's source budget reflects the worker's 25% cash/exposure caps. Robinhood's reported buying power is not treated as settled cash or proof of position headroom.

These calculations are conservative V1 source-model observations only; the actual V2 deterministic policy, broker minimum order sizes, account settlement restrictions and executable order adapters still require verification. The original V1 broker workers remain the only live writers and no V2 live order permission was granted. V2 core is 2.0.0-alpha.12.

## v1.3.15 — New continuously supervised V2 Schwab stock shadow worker

The existing Schwab scanner now publishes only the five-minute completed price history it already fetched to a separate private V2 directory. A new V2 stock shadow worker consumes those source candles with source-timestamped quotes and evaluates the shared StockController. Qualified candidates can receive bounded local Ollama shadow evidence. Results are durable, duplicate-safe, and visible in Trading Operations across all 24 Schwab stock symbols.

This is strictly observational. It neither makes a second Schwab API call nor uses a broker or simulated order adapter. No exchange session, executable broker quote, settlement or live risk rule is implicitly verified; the existing Schwab V1 worker remains the only authorized live writer. Since equity markets are closed on Saturday, fresh production stock candidates/AI reviews are not claimed. V2 engine 2.0.0-alpha.11 is still non-live for broker orders.

## v1.3.14 — One Schwab quote fetch, two isolated consumers

The existing Schwab V1 stock scanner now saves a sanitized owner-only copy of the actual quote batch it already requested so the V2 MarketDataProvider can validate quote source, symbol, exchange time and bid/ask without a second OAuth connection. V2 market observations remain NON_EXECUTABLE and do not control real brokerage orders.

The V2 preflight remains visible for all brokers in Trading Operations. No V2 live broker adapter or automatic V1-to-V2 handoff is enabled. On November 21 (Saturday) market-closed verification may continue to report NO_FRESH_QUOTE until an authenticated V1 stock scan collects genuinely fresh exchange-timestamped observations. V2 core 2.0.0-alpha.10 is still paper/read-only for live brokers.

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
