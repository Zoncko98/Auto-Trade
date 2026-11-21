## v1.3.4 — TrueNAS Schwab reauthorization marker compatibility (2026-11-21)

- Corrected the Schwab OAuth reauthorization status file writer after production testing showed the existing TrueNAS live-state directory uses mode 0755. The status file itself remains owner-only 0600; group/world-writable directories are refused.
- Added a regression fixture matching the actual TrueNAS directory permissions and preserved the no-secrets token fingerprint.
- Production had demonstrated a rejected Schwab refresh token and empty new-order submissions. A bounded private REAUTH_REQUIRED marker was created after validating the observed OAuth error, immediately preventing further automatic refresh retries. No token content was read or altered.
- Existing V1 brokers, order journals, user settings, V2 paper-only gate and deployment remain unchanged except for this compatibility correction. Broker reauthorization still requires authorized user interaction and valid OAuth consent.

## v1.3.3 — Schwab exit priority, OAuth reauthorization states and truthful UI (2026-11-21)

- Fixed the critical legacy Schwab issue in which the combined daily-order cap returned before existing-position sell signals were evaluated. Held positions and verified exit signals are now evaluated first, while new entries still stop at the original combined-order ceiling.
- Added an independently owner-editable, conservative daily exit-order allowance (default 3, maximum 30), with an explicit limit and transparent rejection evidence in the existing Schwab Risk & Start UI. All broker market-session, verified-quote, held-position, settlement, reconciliation and idempotent journal controls remain in force.
- Existing eight- and nine-field risk documents are accepted through an in-memory migration, preserving all original saved exposure limits and revisions without rewriting settings during startup.
- Added a private, nonsecret Schwab refresh-token revocation marker tied to token file metadata. A rejected OAuth refresh token now stops autonomous restart attempts until it changes; a subsequent authenticated account lookup clears the marker. No broker token or response payload is persisted.
- The V2 read-only broker status distinguishes REAUTH_REQUIRED from ordinary worker downtime; account UI distinguishes configured order permission from actual execution readiness and directs the user to Broker Connections.
- Added synthetic limit-priority, OAuth rotation, security, legacy policy, and UI tests. No live order was submitted to validate these fixes. V2 live writer cutover is still disabled; legacy workers and their journals are preserved.

## v1.3.2 — V2 Phase 3 advisory AI and historical synthetic replay foundations (2026-11-21)

- Added a shared, typed AI reviewer for the same V2 paper pipeline. Rejects malformed decisions, wrong symbols, stale quotes, expired signals and oversized payloads; caches short-lived advisory reviews; does not place orders or override deterministic risk.
- Added bounded Ollama chat/JSON transport with fixed model selection, deterministic model options, explicit transport timeouts and validated response envelopes. Runtime connection and model reliability are not yet verified.
- Added synthetic historical candle replay through the existing stock/crypto controllers, V2 risk engine, persisted order intents and simulated broker, reporting fills, blockers, after-cost account equity and gross buy-and-hold reference.
- Corrected historical replay's simulator clock and fractional crypto simulated-cash precision, with regression tests for determinism, costs and time ordering.
- Expanded V2 status diagnostics to distinguish available Phase 3 libraries from unwired runtime capability. Legacy broker workers and order journals remain untouched. V2 live-order authority stays disabled, and no live broker orders were submitted.
- Do not interpret synthetic replay as broker quote replay, live-path validation, or evidence of profitability. Real historical feeds, broker reconciliation, frontend parity and account-specific live cutover remain outstanding.

## v1.3.1 — V2 Phase 2 read-only broker and market normalization (2026-11-20)

- Implemented source-specific owner-only read-only account adapters for Schwab, Webull, Robinhood Crypto and Paper; consistent auth, heartbeat, permission, provenance and reason codes.
- Reject stale observations, rotated Webull credentials, wrong account selections, invalid balances, oversized or world-readable files, and symlinked private state. Align Schwab online readiness with its 120-second worker heartbeat.
- Robinhood buying power is separate from cash/equity; Webull exposes real cash/exposure budget. Unknown values are not interpreted as zero.
- Implemented read-only Schwab, Webull, Robinhood and Coinbase quote parsers requiring actual exchange timestamp, valid bid/ask and freshness. Coinbase midpoint never substitutes for an executable last trade.
- Implemented completed-candle replay parser and cached MarketDataProvider protocol adapter. Sources make no extra broker SDK calls; market session and execution authority remain disabled.
- Added authenticated Phase 2 broker/source status to the existing Trading operations panel, without adding another account dashboard or order controls.
- Expanded Python market/provider and account contract tests and JavaScript UI tests. V1 broker workers, policies, journals and accounts are unchanged. V2 remains paper-only and disabled by default.

## v1.3.0 — V2 Phase 1 paper-only foundation (2026-11-20)

- Implemented experimental V2 core with typed canonical accounts, capabilities, market snapshots, normalized candles, candidates, AI reviews, risk decisions and durable order intents.
- Added private V2 SQLite journal with WAL, synchronous FULL writes, transactional append-only events, idempotency fingerprints, validated transitions and UNKNOWN_REQUIRES_RECONCILIATION.
- Added separate deterministic stock and crypto controllers, and a shared risk service that evaluates risk-reducing exits independently of entry-count/loss limits.
- Added persistent simulated broker for whole-share/fractional virtual fills, cash, positions, fees, slippage and broker-side idempotent lookup. V2 paper pipeline requires SimulatedBroker and cannot invoke real brokers.
- Added reproducible synthetic smoke demo, 32 Python regression tests (including authenticated status API), and browser UI checks.
- Added signed-in read-only V2 status API and collapsed foundation details under existing Trading operations. AUTO_TRADER_V2_ENABLED defaults to false; no V2 live-broker order authority exists.
- Original Schwab, Webull, Robinhood and paper V1 workers, credentials, risk policies and journals are unchanged. No live trades submitted to validate V2.

## v1.2.5 — Recoverable Schwab worker lifecycle and truthful readiness (2026-11-20)

- Diagnosed running TrueNAS v1.2.4 deployment without resetting data. Schwab live worker heartbeat and account snapshot were stale for approximately 23 hours, though all 19 journal orders were terminal and operator order permission remained running.
- A Schwab pre-order LiveBlocked condition now records a blocked, unarmed heartbeat and explanatory scan-health record and retries on the normal five-minute scan schedule, only when the existing journal is complete and unhalted.
- A stopped Schwab subprocess may relaunch after a bounded 120-second backoff only when an explicitly enabled account has an unhalted order journal with no unresolved or replaced orders. At most three such restarts per hour; other states demand reconciliation or operator review.
- Journal fsync-before-POST, broker reconciliation, authentication, risk controls, AI gates, account cash, order minimums and duplicate-order prevention remain unchanged. No test order is submitted.
- Supervisor lifecycle and scan-block reasons are visible in authenticated Schwab dashboard; status files are atomic and owner-only.
- Preserved Robinhood risk/fee filters and Webull user-controlled disarmed policy; no automatic broker reauthorization or forcing of trades.
- Added tests covering transient scan errors, ambiguous order refusal, restart budget, status persistence and UI readiness.

## v1.2.4 — Owner-controlled Schwab risk ceilings (2026-11-19)

- Made Schwab live strategy capital an explicit user-editable amount rather than an immutable $100 ceiling, while limiting usable strategy capital to the lower of saved capital and broker-verified account equity.
- Expanded live risk settings for per-order dollars, percent position size, daily drawdown, simultaneous holdings, daily buys, daily total orders, and reporting-only growth objective. Every field is editable in the existing Schwab Risk & Start page.
- Removed silent $25 per-order, 25% position, $5 daily loss, 3-position, 3-buy and 7-order live-worker clamps. New per-order dollar budgets still never exceed verified non-borrowed cash, available strategy headroom, saved position percentage, and validated order limit.
- Preserved whole shares, minimum quote quality, settlement restrictions, per-account authorization, AI approval, one unresolved order rule, journal fsync-before-POST, no shorts/options/margin borrowing, daily-loss cutoff, and broker order reconciliation.
- Automatically read legacy eight-field live risk documents using the existing $100 strategy-capital ceiling. New validated saves use nine risk fields with atomic revision control; rollback preserves original settings.
- Added cash/capital-consistent dashboard preview and explicit confirmation before increasing live-money risk. The user must save changes; UI controls do not silently increase settings.
- Verified synthetic higher-budget order sizing, stricter remaining-capital behavior, operator daily loss thresholds, configuration migration, and journal safety. No live test orders were submitted.

## v1.2.3 — Schwab stale-market-data recovery and live account monitoring (2026-11-19)

- Prevent a temporary missing or stale five-minute candle for any existing Schwab holding from killing the live worker. If any held position's completed candles are unavailable, block ALL orders in that cycle and write a decision reason; retry on the normal scan schedule.
- Keep broker authentication, order journal reconciliation, market hours, risk limits, exposure, and duplicate-order prevention untouched.
- Refresh Schwab's authenticated account/positions/equity snapshot every 60 seconds while operator order permission is paused, without submitting or reconciling orders in the paused path.
- Report a paused but online Schwab monitor accurately on the account readiness panel and workspace tile.
- Keep the supervisor's explicit no-auto-restart rule for other stopped real-money workers, logging the stop once instead of flooding logs every four seconds.
- Add tests for stale held-asset market data, fail-closed execution, paused-only refresh cadence, and accurate UI status.
- Operator authorization will be placed in the paused state before production restart for read-only verification. Re-arming requires a deliberate Start action in the dashboard.

## v1.2.2 — Webull quota and Robinhood order-history recovery (2026-11-19)

- Handle Webull SDK HTTP 429 in dashboard authorization and portfolio API with an actionable 503 response instead of a connection-aborting 502.
- Use a fresh, credential-validated Webull worker account snapshot for policy authorization only. Independently verify all broker permissions, cash, risk, positions and orders before execution.
- Reuse a short-lived dashboard-only Webull SDK client to reduce app-key quota usage.
- Raise only Robinhood order-history pagination ceiling from 50 to 250 after observing 1,001 records over 51 pages. Preserve cursor validation and fail closed on truncation.
- Keep Robinhood's scanner heartbeat reporting when broker order history fails; block all order submissions until authoritative reconciliation succeeds.
- Make the interface distinguish unavailable history from offline worker status.
- Add regressions for pagination, stale history, snapshot credibility and credential rotation; no live order tests.

## v1.2.1 — Mobile workstation and Robinhood USDC portfolio valuation (candidate, 2026-11-19)

- Made all four existing broker dashboards touch-first: compact cards, uniform account picker, bottom Overview / Risk / Activity navigation, accessible details, consistent portfolio and trading controls.
- Corrected misleading Robinhood Partial $0.00 when the account has holdings but none can be priced. Unpriced holdings are explicitly labeled unavailable rather than zero.
- Added fresh, display-only CoinGecko USDC/USD indicative fallback when Robinhood's signed v2 bid/ask endpoint cannot quote a broker-reported USDC position. Validates source identity, timestamp, positive finite price, and fails closed when stale or offline. No use in execution, AI decisions or risk gates.
- Surfaced the held coin and valuation source in an at-a-glance Robinhood holding row. Cost basis and P/L remain unavailable without verified fills; no synthetic profits are shown.
- Added tests for live quote failure, malformed/stale price data, no-price handling, unchanged order safety, mobile navigation and four-account responsive layouts.
- Source candidate and verification evidence are separate from real brokerage fills. No market orders are created by this feature or its tests.

## v1.2.0 — Unified broker workspaces and trade diagnostics (source milestone, 2026-11-05)

## Unreleased — Unified trader workspace & simplified activation (feature branch, 2026-11-18)
- Use one compact, responsive broker dashboard structure for Schwab, Robinhood Crypto, Webull and paper trading; promote Start/Pause/Risk, four portfolio metrics and performance, with optional expandable holdings, diagnostics and activity.
- Replace duplicate broker sidebar trees with one account selector and consistent Overview, Risk & start, Orders & activity paths; fold shared tools, extra actions, tile ordering and planned integrations behind disclosures.
- Separate saved risk/explicit operator authorization from transient execution gates: permit Robinhood and Webull scanning authorization without requiring immediate account cash/order readiness; preserve fresh order-time broker, funding, account, min size, strategy, loss, exposure and duplicate-order validations.
- Allow locally persisted pause/disarm even during temporary Schwab/Robinhood/Webull connectivity outages; show specific Webull policy validation errors.
- Add unified frontend contract checks, Robinhood underfunded-order/offline-pause regression tests and browser preview verification.
- No live brokerage trade, broker fill or production deployment is implied by this candidate branch.

## Webull order-readiness diagnostics and account permissions (2026-11-12, candidate branch)
- Read-only diagnostic confirms cash-funded stock buying headroom including the existing 25% total-market exposure ceiling and whole-share affordability.
- Filters unaffordable stock entries before AI review, while preserving independent Schwab-mirror stock signal criteria, original broker risk limits, and order restrictions.
- Shows explicit no-order reasons, stock funding and crypto permission within existing Webull dashboard and Risk controls.
- Permits explicit confirmation of changes to already-armed Webull markets; backend requires a new authorization confirmation whenever a new market or account becomes permitted.
- Adds bounded daily signal/session/AI/order rollups for 14 days without changing the underlying order journal.
- Does not automatically enable crypto trading or promise broker order acceptance/fills.

## Robinhood live-entry quality guard (2026-11-12, candidate branch)
- Uses observed broker fee rates and executable quote spread to reject buys with inadequate configured profit budget.
- Rejects new buys with spreads above 0.20%, insufficient 10-minute rising momentum confirmation, late +1.6% momentum, or cached Coinbase quotes.
- Limits to six filled buys per rolling 24 hours, stops new buys after four recent verified consecutive losses, and cools off assets with two verified losses in 48 hours.
- Preserves risk checks, broker minimums, order reconciliation, stop-loss, exit handling, and independent operator controls.
- Shows guard thresholds in the existing Robinhood Risk & trading controls view and trade-specific blocks in execution diagnostics.
- Protective brakes reduce churn but do not prove improved profitability; assess real results before changing thresholds.

This is a source-code milestone based on 132 commits since v1.1.10. It is not evidence that the mutable `:stable` image or the existing TrueNAS app has been upgraded. No live brokerage order was placed to validate this documentation release.

### Broker workspaces and operator visibility
- Aligned the four existing Schwab, Robinhood Crypto, Webull, and Paper Trading dashboards: workspace tiles, portfolio/holdings sections, navigation, card spacing, trade history and account-specific risk/decision controls. No additional combined dashboard was introduced.
- Consolidated connected-account indicators in the account overview sidebar and AI model/readiness status in the top bar; improved refresh behavior, responsive navigation, and error/status labeling.
- Added broker-aware trading-operations and order lifecycle evidence including pending orders, reconciliation, exits, and historical performance views.

### Broker-specific integration and risk controls
- Added authenticated Robinhood Crypto account/position display, guarded live buy/sell routing, worker lifecycle controls, order journaling/reconciliation, and independent risk/authorization gates.
- Added Webull account discovery, holdings, stock/crypto quote and feed diagnostics, operator controls, and guarded order pathways. Webull stock evaluation uses an independently configured mirror of the shared five-minute stock strategy; broker permissions and data entitlements still apply.
- Added safety checks for stale prices, duplicate/unknown order state, account-level buying power and exposure, broker-reported minimums, and external sales; retained separate live and paper controls.
- Made Robinhood news optional as supporting evidence when a technically eligible crypto candidate has no timely coverage; negative news/risk gates and AI review remain in place.

### Performance diagnostics, quality and operations
- Added an authenticated Robinhood Excel performance export with trade-level fees, outcomes, and AI/entry evidence.
- Added fee-aware *shadow* strategy/entry diagnostics measuring spreads, candidate conditions, favorable and adverse excursion (MFE/MAE), holding time, exit reasons, and net-after-fee return. Shadow evaluations do **not** automatically change live execution.
- Expanded regression and CI coverage for broker account boundaries, frontend navigation and rendering, worker recovery, order reconciliation, and diagnostics. Corrected low-risk release/CI/documentation issues.
- Updated the README with privacy-redacted screenshots captured from the existing TrueNAS UI. These images illustrate a previously deployed app build, not an independently verified v1.2.0 installation.

**Validation boundary:** source integration and tests are not proof of broker-accepted/filled orders, strategy profitability, portable installation success, or production image identity. Do not mark live execution verified based on this milestone. A stable version tag, production update, and broker-side acceptance verification are separate steps.

---

## v1.1.10 - Correct shared paper AI routing and historical audit labeling

- Map saved Ollama provider to the shared local news-classifier AI route for the paper account only.
- Label inherited legacy paper reviews as historical within the existing account audit.
- Preserve fail-closed AI and never submit live orders during tests.

## v1.1.9 - Shared brokerage worker / virtual paper account

- Reuse live_worker.py for account-specific Schwab and Paper Trading execution.
- Share candidate selection and AI decision logic; paper orders use a virtual brokerage adapter, never live submission.
- Keep one authoritative paper_account.json ledger with isolated virtual fills, account discovery, and independent controls.
- Remove duplicated Paper Lab frontend controls and its scheduler.
- Retain existing Schwab order safety gates; Robinhood and Webull remain unavailable adapters pending supported integration.
- Production verification must confirm read-only Schwab market-data access and an independently running paper account.

## v1.1.8 - Correct paper market-feed telemetry

- Paper worker reports source observation count, last check, feed enablement and unavailable symbols in runtime heartbeat.
- Existing dashboard distinguishes functioning public market feed from missing data. AI reviewer timeouts remain real vetoes.

## Historical version status

Every tag before v1.1.7 is deprecated because the paper workflow was incomplete or malfunctioning. Tags remain for historical inspection only. v1.1.7 is experimental and is not certified for profitability or live execution.

## v1.1.7 - Paper worker and market data repair

- Paper worker now receives the exact local Ollama /api/generate endpoint it requires, without changing live worker settings.
- Paper-only supervisor retries failed paper children with a cooldown and reports child exit codes; does not restart broker workers.
- The existing paper account ingests completed, source-timestamped public crypto and equity minute bars when its strategy is Running; stale or missing quotes are rejected.
- Includes a bounded atomic price CSV, per-market feed status in the existing paper dashboard, and synthetic plus real-market smoke tests.
- Paper trades remain subject to deterministic limits and fail-closed AI review, independent of live brokerage actions.

## v1.1.6 - Integrated Paper Trading research

- Forecast interface and controls are now in the main Paper Trading workspace.
- Removed duplicate Paper Lab page and virtual-account display.
- Research forecasts never alter the existing paper account or Schwab execution.

## v1.1.5 - Paper Lab configured-model integration\n\n- Paper research now uses saved private Ollama URL and selected model.\n- Manual runs and opt-in scheduling share model configuration; unsupported providers fail closed.\n- Paper Lab link moved from fixed overlay into normal page flow.\n\n## v1.1.4 - Unified paper research\n\n- Stocks and crypto AI predictions, paper outcome evaluation, and authenticated dashboard interface.\n- Manual research controls plus opt-in hourly automatic predictions. Daily $1 target tracking and maximum drawdown. No paper fallback to live execution.\n- Results are hypothetical, not validated executable trade profitability.\n\n## v1.1.3  Crypto AI research adapter

- Connects the isolated crypto prediction lab to existing local Ollama and Open WebUI chat interfaces via validated JSON directions and horizons.
- Read-only, manually invoked research cycle; collects completed public hourly closes, scores matured previous predictions and locks new model output before future outcomes.
- Unsupported or offline model providers fail closed. No crypto exchange credentials, Schwab data, simulated fallback, or orders.
- Separate UI and authenticated dashboard integration remain future work.

## v1.1.2  Isolated crypto prediction research core

- Added independently stored, time-locked BTC/USD and ETH/USD forward predictions, with 1-, 4- and 24-hour horizons.
- Added public Kraken hourly OHLC ingestion, excluding the potentially incomplete latest candle.
- Scoring waits until the future outcome candle is complete; original predictions are never revised in place.
- Includes explicitly hypothetical $100 long/short directional notional calculations with 20 bps fee and 10 bps slippage per side. DOWN is analytics only, not an executable short order.
- Supports source labels for externally generated AI predictions or simple baseline comparisons; it does not claim to run an AI model by itself.
- Strict isolation: no Schwab integration, broker actions, execution fallback, paper-to-live migration, or account-balance mutation.
- Four tests with synthetic price observations; no paper or live brokerage orders.
- Research-core release only. No UI changes; UI integration can be handled by the parallel visual agent.

## v1.1.0 — Unified trading workspaces and streamlined setup

This version integrates the complete v1.0.18 stable trading engine, AI position reviews and model readiness with the accessibility and user-experience work below. Existing broker tokens, real-money trading authorization, positions and risk limits are preserved in persistent storage. The UI is a presentation and authenticated configuration update, not an automatic change to order execution.

### Login, installation and broker navigation cleanup

- Reduced the minimum length for NEW dashboard administrator passwords from 20 to 10 characters. New passwords require an uppercase A–Z letter, number and symbol (up to 256 characters). Both the server and browser enforce the rule. Existing passwords remain valid; PBKDF2 protection, login rate limiting and session invalidation are preserved.
- Simplified first-run installation to account claim and AI model/provider selection. Forecasting uses the built-in NAS default. Schwab OAuth, background modules and trading permissions are no longer part of first-run.
- Profile now links to AI & Forecast Settings only. The existing Schwab developer credentials, callback flow, read-only quote monitoring, account selection and real-money activation are on the new authenticated broker-specific page accessible from Broker Connections.
- Page-specific settings updates preserve unrelated AI settings, broker secrets and live-trading configuration. Neither settings page can accidentally clear the other one's fields.
- Added explicit Paper → Risk Settings control to enable/disable the separate background paper simulator without placing this option in installation or Schwab authorization.
- Added end-to-end and browser payload isolation regression tests, with the new tests included in the GitHub Actions workflow.
- Integrated on the v1.0.18 codebase. No live-trading authorization defaults, account choices or execution permissions are changed by this release.

### Workspace account tiles (feature/workspace-account-tiles)

- Replaced the sidebar Live/Paper dropdown with visually distinct selectable account tiles. Schwab Live opens the existing live overview and Paper opens the existing simulator, each preserving its dedicated navigation, risk controls and account history.
- Added greyed-out, non-clickable Coming Soon tiles for Webull, Robinhood, Alpaca and Interactive Brokers. These are interface placeholders, not real brokerage connections or order routes.
- Shows a conservative Schwab connection hint from authenticated /api/brokers capability metadata (AUTH SAVED vs CONNECT ACCOUNT); a stored OAuth file is not evidence that an active broker session or order permission is valid.
- Added selected-account highlighting, keyboard-focus and ARIA pressed states, mobile compact tiles, small-screen layout refinements and reduced-motion treatment.
- Added freshness-checked equity badges: paper simulator equity and Schwab broker equity only for an online worker with a recent valid account snapshot; unavailable values never show fake $0.00. Balance text clears on logout.
- Replaced letter placeholders with pictograms and retained the paper wallet icon. Added the unmodified Alpaca external-use brand kit asset. Other providers use neutral symbols pending clear logo permissions; provenance and reuse restrictions are recorded in docs/guides/workspace-tiles.md.
- No credentials, risk settings, order code, broker selection, trading authorization or production deployment were changed.
- Combined into v1.1.0 and validated against the v1.0.18 trading safeguards.

## v1.0.18  Recurring advisory AI reviews for live positions

- Added periodic (15-minute minimum per symbol) structured AI news assessments for already-held live positions.
- Uses the existing strictly validated live AI-review response schema; missing, malformed, or unavailable responses remain fail-closed for new BUY entries.
- Position review outputs are explicitly advisory, never automatic SELL commands; existing independent downward-crossover and authorized protective exits take priority.
- Records bounded, non-secret position AI review telemetry to the existing private live-state volume, without sending holdings or account data to the AI.
- Adds four isolated unit tests with mocked AI providers. No paper trades or live test orders.
- Does not yet verify structured capabilities for all configured cloud providers or implement AI-generated SELL/REDUCE execution. These require separate validation.
- Does not modify live settings or redeploy TrueNAS.

## v1.0.17  Verified local AI model metadata and readiness UI

- The authenticated readiness API now queries the configured private-LAN Ollama /api/show endpoint with a five-second timeout and bounded response size.
- Validates actual model parameter_size metadata rather than trusting the model-name suffix; unknown, undersized or unavailable models are explicitly reported as unverified.
- Dashboard sidebar shows SIZE VERIFIED, BELOW 4B or AI OFFLINE with clear limitations.
- No inference payload, account data or broker credentials are sent during metadata validation.
- Metadata verification is not a structured-response capability test and does not yet change live entry authorization; the existing fail-closed AI news veto remains in force.
- Added mocked unit tests for verified metadata and provider failure. No paper or live orders were placed.
- Existing live position SELL protections and risk settings are untouched.

## v1.0.16  Visible AI configuration readiness

- Added an authenticated sidebar AI readiness indicator and failure/uncertainty explanations, refreshed every 30 seconds.
- Explicitly differentiates a model-name claim from verified model metadata or a working AI connection.
- Preserved the existing fail-closed AI research veto on new live buys; existing rule-based protective sells remain independent.
- Does not assert runtime readiness, implement model metadata verification, or enable a new live trading gate until these mechanisms can be validated.
- No paper trading or real order execution was performed during validation.

## v1.0.15  Read-only AI compatibility diagnostics (stage one)

- Added authenticated GET /api/ai/readiness with non-secret model/provider compatibility status.
- Local Ollama model-name parser flags claims below the proposed 4B minimum; name alone does NOT verify actual parameter count, readiness or capability.
- Cloud selections are reported as needing runtime verification, not falsely marked healthy.
- No credentials are exposed. No AI calls are made by the endpoint.
- Added five targeted tests for 4B, subminimum, unknown size, cloud and missing provider.
- No new trading gate or runtime enforcement: existing live orders, risk controls, authentication and settings remain unchanged.
- Future stage: authoritative metadata and structured response probes, then separately validated live enforcement.

## v1.0.14  Advisory technical indicator research

- Added deterministic 14-session RSI, 12/26 MACD and nine-session signal, a close-only 14-session volatility range proxy, and relative volume compared with the previous 20 sessions.
- Added a clearly labeled symbol-only trending/ranging/volatile regime proxy; it is not a broad-market regime assessment.
- Attached advisory indicator data to NAS-native read-only forecast research for candidates with sufficient validated history.
- ATR is explicitly labeled a close-only proxy because the historical feeds currently use close/volume bars; it must not be confused with true OHLC-based ATR.
- Added four regression tests covering indicator bounds, insufficient data, invalid close and flat prices.
- Kept all live entry selection, AI veto policy, risk controls, order sizing and broker authorization unchanged. Indicators do not automatically trigger orders.
- No production deployment or live-order tests performed.

## v1.0.13  Explainability update release validation

- Updated the profile version regression test to compare against the application VERSION file instead of hard-coding v1.0.11; this keeps the test valid for subsequent releases.
- Preserved the v1.0.12 code and immutable tag. v1.0.12's image publication failed due to the version-specific test assertion.
- Published the explainability changes under a new immutable release version after correcting validation. No changes to execution behavior.

## v1.0.12  Explainable trade decision records

- Added app/trade_explanations.py for structured, observable trade evidence; no private model thoughts are claimed.
- Paper trading reviews now record the crossover strategy, AI response, risk flags, and decision timestamp.
- Live entry audit evidence includes technical reasons, AI verdict, and up to eight ranked alternatives.
- Screened-but-not-selected alternatives are not misrepresented as confirmed failed entry signals.
- Invalidation levels are only recorded when explicit validated data is available, never invented; no automatic stop order is added.
- No fabricated confidence probability. Existing execution, risk, authorization and cash-only protections are unchanged.
- Four standalone tests added. No TrueNAS production deployment or live execution testing was performed.

## v1.0.11 — Sidebar installed-version display

- Replaced the bottom-left sidebar sentence about the Schwab worker and dashboard order submission with a live Auto Trader vX.Y.Z version label.
- Version comes from the authenticated, local /api/profile endpoint after login, so it always reflects the installed app, not the latest GitHub release or TrueNAS custom catalog metadata.
- If version lookup is unavailable, the footer shows a clear fallback rather than an outdated hard-coded version.
- No changes to broker connections, order permissions, risk limits, credentials, or deployment topology.

## v1.0.10 — Multi-broker workspace foundation

- Added a new authenticated **Broker connections** view to the single TrueNAS Auto Trader app, accessible from both live and paper workspaces.
- Verified and documented official API routes for Schwab, Webull Connect/OpenAPI, Alpaca Connect, Interactive Brokers and Robinhood Crypto. Clearly distinguish published provider capabilities from real integrations and account authorization.
- Introduced a typed Python BrokerAdapter contract covering accounts, balances, positions, market quotes, order history, submission and cancellation. All non-Schwab adapters explicitly fail closed; no new live trade execution has been enabled.
- Exposed authenticated GET /api/brokers returning non-secret capability and integration metadata. The Schwab badge reflects only presence of a saved authorization file, not proof of a valid current broker session.
- Added the provider documentation links, exact API access prerequisites, asset-class restrictions and phased integration plan under docs/guides/multi-broker.md.
- The existing Schwab OAuth workflow, live worker, cash-only restrictions, risk controls, paper engine, AI model settings, trade histories and TrueNAS deployment are unchanged. No new brokerage password/API key is collected.
- Added tests for unsupported-adapter fail-closed behavior, credential non-disclosure, broker feature claims and integration statuses.

## v1.0.9 — NAS-native market forecasts and selected-provider commentary

- Implemented a no-extra-model NAS-native daily market analysis engine inside the single TrueNAS app, with genuine historical data feeds, eligibility screens, technical momentum/trend/volatility/liquidity calculations and illustrative historical-volatility bands.
- Added a second public price-history feed fallback, dated persistent cache, background fetching and explicit incomplete/stale state. No speculative prices are generated when market data is absent.
- Added Automatic, Built-in NAS and Advanced Workstation forecast modes. Existing specialist Chronos/LightGBM/FinBERT forecasting remains optional.
- Added opt-in qualitative public-news interpretation using the user's already selected Ollama or ChatGPT/Gemini OAuth companion. The model cannot modify prices, scores or trading eligibility. Existing cloud OAuth requires a LAN companion; direct native cloud OAuth login is not implied.
- Updated forecast UI to distinguish historical-volatility bands from advanced scenario quantiles, display relevant source/model, provider commentary when available, and helpful setup errors.
- Continued the first-run wizard into Schwab OAuth onboarding, with optional skip. Included explicit forecast explanation, connection test, workstation setup and security guide.
- Added no-AI, provider-schema, deterministic data and regression tests. No changes to brokerage trading permissions or live order logic.

## v1.0.8 — Schwab redirect copy-and-paste repair

- Fixed incorrect callback mismatch errors when the developer-app callback is https://127.0.0.1:8182 but the browser adds the standard root slash and returns https://127.0.0.1:8182/?code=...&state=.... These root paths are equivalent for validating the returned redirect; the exact callback sent to Schwab remains unchanged.
- Preserved strict HTTPS, host, port, non-root path and OAuth state comparisons, so redirects from another host or unrelated sign-in sessions are still rejected.
- Improved error messages to distinguish callback base-address mismatches, expired/different authorization sessions, missing authorization codes and token-exchange failures. Code/state values are never shown in errors.
- Trim harmless surrounding whitespace from browser-copied callback addresses.
- Added regression tests for root-slash acceptance and rejected wrong port, host, scheme, path, and fragment.
- Does not change Schwab developer-app settings, credentials, stored tokens, positions or live order permissions.

## v1.0.7 — Installation fixes and simplified live trading

- Fix GUI setup progress: administrator creation is complete independently from optional AI, broker OAuth and module connection states.
- Stop requiring live-trading confirmation words when saving unrelated integration settings.
- Replace the live-trading checkbox and manually typed phrase with one ON/OFF button. ON shows an explicit real-money order confirmation popup and validates the selected Schwab account. OFF pauses order permission.
- Clarify two optional modules: simulated paper trading versus read-only Schwab quote monitoring. The quote monitor can be selected before connecting Schwab and waits for authorization.
- Explain 127.0.0.1:8182 points to the browser computer. A browser connection error after Schwab login is expected without a local listener. Copy the full redirect URL into the integration page.
- Add an optional direct HTTPS NAS callback for developer apps registered to that exact address. Developer callback changes can require Schwab reapproval.
- Prevent OAuth query-code leakage through web access logs.
- Check public GitHub release tags from the GUI, show the repository source link, and document native TrueNAS image update support and custom YAML Source N/A.
- Add regression tests for OAuth callback, live order confirmation, update checks and optional module setup. Existing brokerage credentials and trading data are not included.

## v1.0.6 — Unified TrueNAS app and first-run web setup

- One public container image and stable tag for all Auto Trader components; no separate paper/live/market updates.
- First-run HTTPS wizard for administrator username and password, Ollama, OAuth AI companions, Schwab developer settings, and module selection.
- GUI-driven Schwab OAuth redirect flow and linked broker account selection.
- Paper, market and live functionality remains internal to a single Docker container; no automatic live trading on install.
- Persistent protected credentials and broker state; one-time pairing code shown in TrueNAS app logs.

# Auto Trader change history

[Documentation](docs/README.md) · [System architecture](docs/architecture.md) · [Test status](docs/status.md)

## 2026-10-31 — v1.0.3: Private Docker registry update distribution

- Added GitHub Actions to build/test/version private linux/amd64 dashboard, paper and live-worker container images.
- Stable releases publish immutable version tags for all images and mutable stable tags for dashboard/paper only; live remains version-pinned for order safety.
- Added TrueNAS Apps YAML templates and instructions for private GHCR login, GUI updates and dashboard migration.
- Added .dockerignore protections for image build contexts; no secrets or OAuth tokens are shipped in images.
- No automatic activation of brokerage trading. Existing TrueNAS deployment is not switched without a backup and registry authentication.
- Note: native TrueNAS image-update indicator still requires a successful private-image pull and GUI validation.

## 2026-10-31 — v1.0.2: Manual update status display

- Adds an explicit Software Updates panel within the user profile.
- Displays the installed version, latest stable GitHub version, and host check timestamp.
- Adds a manual Refresh Update Status button that only reads local host-checked state.
- No automatic code installation, broker credential changes, or live-worker modifications.
- Published as a real follow-up stable tag to test the v1.0.1 dashboard update notification.

## 2026-10-31 — v1.0.1: Administrator Profile and private release updates

- Added an Administrator Profile with a dashboard password-change option.
- Changing passwords requires the current password, stores a salted PBKDF2 hash in persistent state and invalidates all existing sessions.
- Added cookie revisioning, change-request rate limits and HTTPS integration tests.
- Added authenticated read-only profile/version endpoints and an Update available notice.
- Added a host-side private GitHub stable-tag checker; GitHub SSH credentials never enter the dashboard container.
- The v1.0.0 dashboard cannot show notifications until this feature is installed once.
- The live brokerage worker and its risk controls were not altered.

## 2026-10-30 / 2026-10-31 — Portable installer documentation (v1.1.0-dev)

- Preserved the current v1.0.0 snapshot and the earlier v0.9.0-beta snapshot as immutable Git tags.
- Published `main` for v1.0.0 and `beta` for the prior build.
- Created `feature/truenas-portable-installer` for installation/portability changes without altering either release tag.
- Added an interactive installer that generates private `config/*.env` values, a local HTTPS certificate, isolated persistent storage, and Docker Compose deployment.
- Added customizable Ollama LAN URL/model, an OpenAI-compatible HTTPS API route and API key, and a separate forecast-service endpoint.
- Added Schwab developer app key/secret and manual OAuth flow; installation **does not** start live orders.
- Added a general Linux/Docker mode so the wizard does not require a TrueNAS `/mnt/POOL/` path outside TrueNAS.
- Added source files for the optional Windows AI workstation, initial tests, Compose validation and GitHub Actions checks.
- Added platform documentation/navigation, operations, security, troubleshooting and architecture references.
- **Status:** v1.1.0-dev documentation and deployment tooling under development; not a tested general-public release.

## 2026-10-30 — v1.0.0: next-session AI research

- Updated dashboard model discovery to the separate Ollama server on the LAN instead of running large AI models on the NAS.
- Confirmed Ollama models available for use by the dashboard, including Qwen and DeepSeek-R1 where installed.
- Installed **LightGBM**, **Amazon Chronos-Bolt Tiny** and **ProsusAI FinBERT** on a separate Windows computer, not as Ollama chat models.
- Added the read-only `/health`, `/api/models`, and `/api/forecast` endpoints on the Windows research service.
- Built an experimental five-candidate forecast refreshed after market close and on Monday pre-open (timezone: America/New_York). Research includes market-data sources, dated news links, forecast price scenarios, illustrative entry/invalidation/2R levels and unmet confirmations.
- Ranked candidates conservatively: a tested LightGBM holdout did **not** beat the zero-return baseline, so its output is labeled *unvalidated* and excluded from rankings. Fallback uses transparent technical rules.
- Added the dashboard **Next session forecast** view; verified the NAS could reach the LAN research service.
- Registered a Windows Task Scheduler startup task for the standalone research service and limited its inbound firewall access to the NAS.
- Preserved broker execution and risk controls: forecast output is **not** an order command.
- **Release tag:** `v1.0.0`, commit `9986003`.

## Pre-forecast version — v0.9.0-beta

- Earlier dashboard with live overview, decision evidence, operator risk settings, local model selection, paper overview/trades/audits and export work.
- Cash-only, long-equity, hard-capped trading-worker order validation, broker reconciliation and fail-closed behavior; dashboard login/session protections.
- The beta source is preserved in branch `beta` and tag `v0.9.0-beta`, commit `de15983`.

## Reproducibility notes

- The old v1.0.0 archive contains installation-specific LAN addresses and was **not** itself designed as a portable install package.
- Public market-data/news sources can be delayed, incomplete or unavailable.
- The optional Windows forecasting code is independent of the TrueNAS/Docker dashboard.
- The installer is not a published TrueNAS Apps catalog listing or an Unraid/Docker Hub image.
- Earlier test suites include legacy tests expecting endpoints removed in newer dashboard versions; consult [test status](docs/status.md).

## Upcoming work (not done)

- Clean-host install and upgrade/rollback integration tests.
- Native TrueNAS Apps YAML or catalog packaging with published images.
- Vendor UI manifests/containers for Unraid, Synology and QNAP.
- Verified end-to-end cloud-AI adapters and stricter provider-specific validation.
- Real-time broker market data integration for forecasts, model calibration and live inference monitoring.
- Additional security audits, licensing and public-release readiness.


## v1.0.4 — OAuth AI bridges, broker data monitoring and public-source preparation

Merged portable installer and registry update setup with v1.0.3 release, and adding provider-specific OAuth + broker-market-data integration.

- Added browser-based ChatGPT OAuth/OIDC companion using PKCE, token validation and independent plan authorization; user-consent test pending.
- Added Google Cloud Gemini OAuth ADC companion, with stricter model and response validation.
- Preserved Ollama remote endpoint and selectable model installation on the AI computer.
- Added read-only Schwab quote collector with protected timestamped cache and live quote display in forecasts.
- Added MIT licensing, public security guidance and full-history credential pattern scan of 218 objects (no matches).
- No automatically authorized trades. Broker entitlements and OAuth real-account tests remain user-dependent.


## v1.0.5 — Public container images and dashboard build correction

- Fix dashboard image build to use repository-root context and deploy/Dockerfile.dashboard, including the web interface.
- Preserve versioned images for all services, mutable stable tags for dashboard/paper/market, and pinned live-broker worker.
- No order execution or operator permission changes.
