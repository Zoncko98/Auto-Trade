## v1.3.60 ? Reconcile both sides of Robinhood V2 estimated quotes (2026-11-22)

- Production GET-only Robinhood V2 estimated-price response initially reported SIGNED_ESTIMATE_IDENTITY_UNVERIFIED on both BTC-USD and ETH-USD; the single-result diagnostic was insufficient to tell absent data from the two bid/ask side rows that can be returned by a side=both request.
- Updated signed quantity-specific estimated-price diagnostics to require exactly one matching side when a single row is present, or exactly one bid and one ask when two rows are present. Both rows must have the selected symbol, exact query quantity, fresh signed timestamps, finite nonnegative quoted fee, valid bid/ask, and acceptable spread. The aggregated bid and ask must also remain noncrossed, within original spread limits and within 1% between the two signed side observations. An ambiguous or crossed response remains blocked and is never replaced by synthetic prices.
- Added precise, redacted states for no matching symbol, duplicate/ambiguous side, crossed prices within or across sides, excessive spread and timestamp/fee mismatch, so the existing Robinhood dashboard can show real broker evidence without leaking prices, IDs or credentials.
- No changes to V2 live order permits or existing top-of-book and independent public trade verification. Estimates do NOT establish broker order executability, acceptance or fills; the original user-approved account-scoped handoff remains blocked when production signed quotes fail current V2 admission gates.
- Added two-sided signed-response and cross-side regression tests; continue to use original TrueNAS single app with backed-up state, V1 broker writers and risk limits.

## v1.3.59 ? Signed V2 Robinhood quote diagnosis, bounded cutover attempts (2026-11-22)

- Added authenticated read-only GET /api/v2/crypto/trading/estimated_price/ for allowlisted Robinhood BTC-USD and ETH-USD diagnostic quantities using the existing signed API credentials. This endpoint has explicit exchange timestamps, best bid/ask, and fee fields; recorded diagnostics are allowlisted reason codes ONLY, never account details, raw quotes, fees, credentials or order IDs.
- Probe compares each signed quantity-specific price estimate's verified timestamp, side, identity, bid/ask ordering, spread and fee presence without relaxing the existing best-bid-ask and independent Coinbase live order gates. An estimate does not authorize a V2 order, establish a fill, or substitute a Coinbase quote for the broker book.
- Robinhood's production signed best-bid-ask currently returns crossed bid/ask for BTC and ETH while the Coinbase real minute-candle source is fresh. Cutover attempt correctly failed before stopping V1 with NO_REAL_SIGNED_QUOTE_AND_CLOSED_BARS. This release adds independent authenticated GET diagnostics to identify whether broker estimated quotes share that defect.
- Limits operator-approved Robinhood cutover attempts to a maximum of 3 per runtime; failed checks preserve original V1 writer and risk controls. Each attempt remains account-digest scoped and has a 90-second backoff.
- Adds pure read-only signed estimate tests, signer/URL/quantity-boundary tests, stale/crossed/fee/missing/duplicate tests and independent probe nonauthorization checks. Dashboard shows sanitized per-pair broker GET-only diagnosis in the existing account section, not a new dashboard.
- No live V2 ownership transfer or broker-accepted order is claimed by a diagnostic or by this release alone.

## v1.3.58 ? User-approved atomic Robinhood V1-to-V2 live writer cutover (2026-11-22)

- Installed an account-scoped cutover controller in the ORIGINAL TrueNAS unified application, with a private compose environment approval bound to the SHA-256 digest of the exact selected Robinhood Crypto account (no raw account identifiers in config or status). This does not authorize a future replacement account.
- A cutover attempt requires an existing armed and authenticated account, fresh signed broker account/holdings/full history/open-order/pair/quote/spot funding proof, original saved numeric risk and V1 exit strategy, complete original order-intent and cooldown inheritance, a running supervised V2 executor, zero unadopted V1 bot-owned lots and an actual valid signed broker read plus independent contiguous closed market candles.
- The original parent acquires the exact V1 account order writer lock to let an in-flight broker POST complete, stops ONLY Robinhood's original V1 worker, verifies the process is absent, repeats the signed broker GET preflight and account/AI/risk/portfolio checks, then atomically transfers the same physical writer owner record with a fresh independent attestation and generation. A failure keeps V1 owner and the parent resumes V1; neither Webull nor Schwab is affected.
- Original saved risk/order caps, all market data/bid-ask limits, broker permissions, open-order blocking and durable V2 journal idempotency remain intact. LivePipeLine now acquires the signed minimum notional and quantity increment of the EXACT candidate crypto pair, not those of a different coin sharing the account.
- Replaced the fixed 0/3 dashboard migration label with a safe owner-derived count, preserving a distinction between exclusive V2 ownership, active signed scan state and an independently accepted broker order. Added redacted actual V2 engine-state reporting. Never infer a fill from a heartbeat.
- Added mocked tests for no approval, wrong selected-account digest, worker missing, V1 legacy holdings requiring adoption, changed writer generation, poststop broker GET failure, real lock sequence and private status. Added signed-pair minimum enforcement and owner-derived dashboard count tests.
- Deployment is via the existing one-app TrueNAS image and explicitly staged config; activating the approved digest triggers an attempted Robinhood cutover, not a forced order. V2 broker writes remain blocked when market/risk/broker gates reject; Webull and Schwab are not force-migrated.

## v1.3.57 ? Wire Robinhood V2 broker execution behind signed owner gates (2026-11-22)

- Connected the original single-instance TrueNAS V2 coordinator to real Robinhood signed execution callbacks. The service is only constructed when the account is operator-armed, V2 exclusively owns its physical writer scope, V1 worker absence is observed directly, fresh signed broker account/holdings/history/funding/session/pair/price gates pass, daily V1 limits are inherited, the original V1 strategy/exit policy is validated and a short-lived account-specific writer handoff is still current.
- Added account-wide signed crypto scanning for BTC-USD and ETH-USD, using the existing public Coinbase independently closed real one-minute candles for strategy input, the official Robinhood signed broker quote and strict independent timing/price cross-check for actual trade decisions, existing shared bounded Ollama JSON AI review, conservative account risk mapping and durable canonical V2 order-intent reconciliation. One scan prioritizes every bot-managed exit before new entries.
- Original V1 bot holdings are NOT silently adopted as V2 positions: if a bot-managed legacy holding exists, V2 cutover remains blocked until its signed opening lot and V2 sell-history baseline are reconciled. External positions never become bot-owned sell capacity. Verified independent V2 fills remain account-scoped and idempotent. Signed account cash and exposure remain mandatory.
- Fixed launch readiness to require at least one fully validated broker-native signed-LAST quote or independently attested signed-bid-ask/real-venue-LAST cross-check, not merely a timestamp present in a quote that failed spread or freshness validation.
- Revalidate newly generated account handoff permits at the actual current wall clock after potentially slow signed preflights rather than the beginning of a scan. Keep existing separate Webull/Schwab live adapters gated and unwired.
- Added offline regression tests covering real production callback owner exclusion, missing signed journal and unauthorized parity, genuine completed public candles, single-account broker scope and quote-timestamp-only rejection. Full Python suite tested before release.
- No broker order has been submitted by V2 and no live V1->V2 account ownership transfer was performed by this release. Existing original TrueNAS V1 live order writers remain active, as required while signed proof is missing.

## v1.3.56 ? Preserve confirmed V2 lot opening and realized-net accounting (2026-11-22)

- Extended the original append-only V2 signed receipt projection to expose a managed position's conservative first verified local fill-confirmation time. Fully closed lots reset the timestamp when a new independently filled position is opened; the old lot's cost, time and trailing context cannot leak into it.
- Persisted fee-adjusted realized P&L grouped by UTC reconciliation date. The field explicitly names the reconciliation date, NOT the broker's original execution timestamp, which may differ after a delayed signed GET. This conservative provenance prevents treating quote poll time or an invented broker execution time as proof of a current lot's minimum holding period.
- All quantities, partial fills, average-cost allocations, sale fees and realized gain/loss still originate in independently reconciled V2 order receipts and the original durable intent fingerprint, not ACKs, unsigned quotes or paper fills.
- Verified via tests that a completely sold position clears its opening time and a new buy creates a new lot, signed partial fills are not double-counted, and original account journal tampering or over-selling remains blocked.
- This release prepares the remaining V1-to-V2 managed inventory adoption and signed exit parity implementation; it does not transfer V1 holdings, enable any V2 live broker writer or claim order acceptance.

## v1.3.55 ? V2 pre-submission recovery and Robinhood native quote parity (2026-11-22)

- Closed an execution deadlock: a V2 order with a freshly persisted intent may lose exclusive account handoff or its broker quote before any POST. The original code returned BLOCKED but left INTENT_PERSISTED permanently unresolved. Now it persists a terminal REJECTED original-intent event with explicit broker_post_attempted=False, allowing later valid independent candidates without resubmitting the rejected idempotency key.
- If that terminal journal write fails, the original intent remains unresolved and requires reconciliation. Actual SUBMITTING/UNKNOWN_REQUIRES_RECONCILIATION states are unchanged and never automatically retried or cleared. Every check still occurs while holding the exact V1/V2 account writer lock.
- Harmonized Robinhood signed native-LAST quote validation with the independently attested signed-bid-ask path: native signed venue quotes must be <=20 seconds old and have bid>0, ask>=bid and spread <=1.5%. Fresh signed GET without valid executable book does not become a V2 trading signal.
- Updated the signed Robinhood migration preflight to apply that same native-source spread/age validation before counting a quote. All Webull/Schwab independent stock funding/session restrictions remain unchanged.
- Added mocked live-owner handoff loss, durable pre-POST terminal recovery, storage-failure retention, duplicate-POST exclusion, stale native quote and wide signed spread regression tests. This release does not transfer account ownership or fabricate a broker fill.

## v1.3.54 ? Production signed Robinhood quote diagnostics (2026-11-22)

- Deployment troubleshooting found real BTC/ETH signed broker best-bid/ask sometimes fails executable quote validation even when authenticated account, V1 signed history and crypto technical signals work.
- Split specific signed quote failures into SIGNED_BROKER_BOOK_CROSSED (broker bid exceeds ask), SIGNED_BROKER_SPREAD_TOO_WIDE (valid positive spread above existing 1.5% hard ceiling), and SIGNED_BROKER_BID_ASK_INVALID (zero or unusable signed prices).
- The authenticated Trading Operations signed migration quote diagnostics already display each broker rejection code, without raw book prices or identifying account information.
- Source tests cover crossed, excessive spread, zero/missing and validated independent last-price cases.
- No broker spread tolerance, account risk, order permissions, duplicate prevention or V1 ownership restrictions were relaxed. This release changes diagnostics only and does not itself enable V2 trades.

## v1.3.53 ? Signed Robinhood spot funding and 24/7 product capability in V2 admission (2026-11-22)

- Corrected the permanent Robinhood V2 admission mismatch between crypto spot execution and US-stock settlement hours. Robinhood's signed active API-tradable Crypto trading account reports USD buying_power as its spendable spot allowance; this is now an explicit verified spot-funding input. It is NOT reported as equity settled_cash.
- The independently signed API-tradable crypto pairs now establish a 24/7 *product capability*, subject to broker maintenance and a separate current executable signed bid/ask, bounded spread, order-history, current AI/risk, exact account ownership and fresh single-writer proof at execution. This change never represents a market-data GET as broker POST acceptance.
- Webull and Schwab still require independently verified brokerage settled funds and stock market session; neither accepts Robinhood's crypto buying-power evidence. All broker order minimums, fees, exposure, duplicate-order and V1?V2 parity gates remain mandatory.
- Authenticated V2 Operations now distinguishes signed spot USD buying power, crypto 24/7 capability, verified order-book pricing and original stock settlement. Added mocked signed-account and cross-broker isolation tests and frontend CI contract tests.
- No V1/V2 owner transfer, new V2 broker POST or broker fill occurred in this release. Robinhood's currently rejected bid/ask spread cannot be bypassed by these corrected funding/session types.

## v1.3.52 ? Register V2 execution coordinator inside original TrueNAS app (2026-11-22)

- Added the dedicated, single-instance V2 account execution coordinator as a supervised original application child, with private redacted health and an exclusive filesystem lock. V1 continues holding every account broker writer lock until an independently attested transfer.
- V2 per-account admission now verifies the original account's armed selection, exact durable V2 owner generation, fresh signed account/holdings/orders/product/quote/funding/session gates, complete inherited V1 order limits and account-specific V1 strategy/exit parity. Only a trusted broker integration can supply the short-lived independently generated handoff and canonical AutonomousLiveScan. There is deliberately no default broker grant or synthetic readiness.
- The authenticated Trading Operations view distinguishes a registered but gated replacement process from live brokerage writer authority, including a redacted admission blocker for each account. No raw account identifiers or credentials are exposed in the worker read model.
- Parent runtime supervises/exits/restarts the replacement process separately with bounded backoff and cleanup, keeping the existing broker workspaces and V1 strategy workers intact. An existing V1 owner or missing signed acceptance remains a hard execution block.
- Added deterministic account-level tests for rejected V1 ownership, disarmed policy, missing broker settlement/quote, missing V1 history, missing strategy parity, wrong grant generation, unchanged original worker activity, health staleness and tainted status, plus a CI-checked frontend contract.
- This release registers the real execution coordinator; it does NOT transfer any live broker to V2, fabricate broker acceptance, supply trading adapter authorization, or submit live V2 orders. Broker session, settled cash, quote and parity blockers remain independently enforceable.

## v1.3.51 ? Authenticated management of stale Robinhood bot-owned GTC BUY orders (2026-11-22)

- Investigated production: one original Robinhood Crypto BUY intent remains locally submitted_unconfirmed and broker-confirmed OPEN for over six hours; this GTC limit buy blocks follow-on autonomous trades and can prevent subsequent exits while unresolved. No assumption of cancellation/fill is made from its age.
- Implemented configurable stale-entry cancellation policy (default 120 minutes; 0 disables; bound 0?1440). Original user authorization remains mandatory. A candidate must be one uniquely matching original journal BUY, with its own signed broker UUID, client UUID, source-timed local intent and a fresh signed Robinhood order row confirming identical account, original IDs, side=BUY, state=OPEN and explicit ZERO filled quantity/executions.
- Actual cancellation uses Robinhood's authenticated existing cancel endpoint under the SAME V1/V2 account writer ownership lock. The local original order is atomically marked cancel_requested before the broker POST, and a timeout or unknown outcome never triggers a second cancellation request. The journal remains nonterminal until a subsequent signed Robinhood broker GET returns a final order state.
- The worker continues to reconcile complete broker history every cycle before evaluating any new order, never treats a partial fill or unsigned quote as cancelable and preserves the exact original intent, opening fills and risk controls.
- Account-specific Robinhood risk settings now display and save the auto-cancel TTL; the existing dashboard reports current stale-order management state rather than conflating an open GTC order with AI or strategy failure.
- Added exact-client identity/UUID, no-partial-fill, age threshold, owner scope, timeout/no-retry, canceled reconciliation, disabled policy and UI contract tests. Does not enable V2 writer ownership or submit new trading orders. The legacy V1 broker remains active until an independently verified V2 handoff.

## v1.3.50 ? Exclusive account owner-aware V1 process lifecycle (2026-11-22)

- Wired the original unified TrueNAS process supervisor to independently inspect each selected broker account's durable V1/V2 writer ownership before spawning or restarting the existing Schwab, Webull or Robinhood worker. If a selected account has a signed local V2 ownership record, its V1 worker will not be restarted; existing V1 account order locks remain in place at the actual broker POST boundary.
- On Webull, verified stock and crypto account scopes remain independent: when a stock account transfers to V2 but a different crypto account remains V1-owned, the original worker stays available for the unrelated V1 account, while every attempted stock POST still hits the precise account-scoped ownership lock.
- A missing, contradictory or unreadable owner record for an active selected account fails closed instead of assuming V1 or silently respawning the worker. No action here grants V2 execution privileges, changes the original user arm or transfers ownership.
- The authenticated V2 Operations view now displays a redacted V1 worker placement reason for every broker, independently of its heartbeat and historical daily risk counts. This makes the eventual V1-to-V2 exclusive process handoff visible without exposing selected account IDs.
- Added account-ownership restart, mixed-account Webull, invalid owner, parent runtime static wiring, broker writer lock and redacted supervisor tests. Existing TrueNAS deployment is updated in place only after CI, with original rollback, risk settings and order journals preserved.
- This release does not arm a V2 live order worker or submit any new V2 brokerage orders; broker-specific full exit/entry parity and signed trading permissions are still prerequisites.

## v1.3.49 - Safely inherit legacy Robinhood signed order timestamps (2026-11-22)

- Production V2 read-only migration observation identified a V1 journal timestamp compatibility problem: some older Robinhood order records omit a local created_at even though their broker-confirmed fill or durable terminal resolution timestamps exist.
- The inherited order-count reader now uses original broker-confirmed filled_at for such FILLED and externally reconciled orders, or the preserved resolved_at for canceled/failed/rejected/expired orders. A filled order counted on its actual fill day can conservatively overcount yesterday's order, but never reset the current day's limits. It never substitutes an arbitrary updated_at or the current clock and blocks missing signed timestamps.
- Redacted UI and supervisor statuses now distinguish a missing signed FILL timestamp from a missing terminal resolution timestamp. No V1 order history is modified, synthesized, or imported as a new broker fill.
- Added regression cases for historical imported fills, terminal rejections, future/absent times and cross-date boundaries. Robinhood remains subject to its original user arm, approved risk, settlement, executable quotes and exact V1/V2 writer handoff.

## v1.3.48 - Stable V2 protective order identity and broker-verified V1 lots (2026-11-22)

- Fixed a critical live-order idempotency hazard: a protective SELL's original V2 order-intent identity is now derived from an exact broker-reconciled bot-owned lot fingerprint (account scope, symbol, opened_at, quantity and weighted cost) instead of each fresh quote timestamp. Risk continues to enforce a current signed quote; a subsequent quote of the SAME lot returns the original persisted intent rather than creating another broker order. Changed signed lots require independent reconciliation and a new fingerprint.
- Added a strict read-only managed-lot adapter for Robinhood Crypto and Webull equities. It checks fresh signed brokerage account/holdings/history gates, exact account match, V1 journal BUY/SELL fill economics, broker-confirmed bot quantity and opening timestamp before supplying a managed lot to V2. Robinhood high-water markers are loaded only when their saved signature matches the current lot. Webull fee, over-sell or mismatched external-holding evidence blocks adoption. The legacy Schwab ledger's historical cost basis is not sufficiently certified for automatic adoption, and remains explicitly blocked.
- The shared V2 scanner now uses those signed V1 lot sources, saved original per-account exit rules and inherited V1 daily order counts by default when no specialized broker provider was configured; it never guesses a missing cash, inventory, fee or cost-basis value.
- Increased bounded default SharedAIReviewer and shadow Ollama review allowance from 8s/6s to 18s, reflecting the existing qwen3.5:4b model's measured ~9s local structured generation in a read-only health test. Market-data freshness and writer handoff are rechecked after review before any order.
- Authenticated Trading Operations now shows the exact redacted V1 inheritance blocker rather than an ambiguous not-verified label. No account IDs or raw order journals are disclosed.
- Added mock broker execution and deterministic unit tests for repeated original lot intent IDs, mixed-symbol/foreign account rejection, missing signed fees, malformed history and model timeout bounds. Existing V1 workers, configured trading permissions, signed broker sessions and all live cutover gates remain unchanged.

## v1.3.47 - Preserve V1 order counts and cooldowns on account migration (2026-11-22)

- Added read-only, account-specific V1 order-history inheritance from the original Schwab JSON ledger, Webull SQLite journal and Robinhood Crypto protected order history. Original V1 BUY/SELL order intents, Robinhood symbol-specific reentry cooldowns (including broker-verified manual/external sales), and Schwab's separate maximum saved daily total-order limit are enforced by V2 before a fresh entry or protective exit.
- The shared autonomous V2 live scanner now requires a typed, signed, fresh V1 account-matched inherited-order record in addition to exact V1/V2 ownership transfer and full strategy-parity proof. Unknown or pending legacy orders, mismatched account selection, expired broker signed reconciliation or missing saved limits block V2 execution; old legacy activity cannot be reset by creating a fresh V2 event store.
- Existing V1 orders and V2 intents are added for both entry and exit rate limits; inherited Robinhood reentry restrictions prevent immediate buy-back after a V1 sale. Schwab's separate combined order/action cap blocks new BUY entries when reached, but V2 still evaluates separately budgeted and broker-authorized protective SELLs, correcting the original V1 exit-starvation defect. These controls do not remove existing broker risk or operator permissions.
- The supervised, authenticated V2 Trading Operations view reports whether inherited V1 daily activity was independently verified and shows redacted BUY/SELL intent counts only when the signed source remains fresh. Supervisor status does not disclose account identifiers or grant live V2 broker writer authority.
- Added broker-specific journal parsing, unknown/future/duplicated orders, manual external sell, same-session settlement and account-history/scope tests. No live V2 brokerage orders or V1-to-V2 writer transfer was performed.

## v1.3.46 - Signed bot-lot protective exits and V1 stock continuation (2026-11-22)

- Added deterministic, broker-specific V2 protective-exit rule evaluations for Schwab's confirmed 3/5-bar bearish crossover and same-day buy hold, Webull's cost/hold/stop/profit/high-water rules and Robinhood Crypto's separately estimated sell-fee and stop-reference costs. Unknown bot-owned cost basis, signed available quantity, opening time or historical receipts block both a SELL and fresh BUY for that account.
- The shared V2 scanner checks eligible held-position protection before new entries. It never sells on an isolated generic downward cross without the verified broker-specific V1 exit condition. For Robinhood/Webull a verified stop-loss can be evaluated even if optional technical candle data is unavailable. All signed account, session, quote, exposure, exit-order limit, independent strategy parity and exclusive-writer checks remain.
- Matched Robinhood's saved max_order_usd per-order SELL ceiling in V2 deterministic risk. New BUYs retain their separate daily-loss, fee, available-cash and AI approval requirements; valid protective SELLs remain independent of entry-only AI or daily entry caps.
- Added moderate 0.4%-2% rising three-completed-bar M5 continuation to the V2 live STOCK controller, matching the existing Schwab/Webull V1 entry option while preserving the separate V2 paper baseline until exact paper/live parity is validated.
- Extended the signed Webull read-only preflight with source-time validated stock bid/ask/last and signed stock-account class evidence during the conservative US core session. Those GET observations DO NOT verify an executable broker order, real exchange session entitlement or permission to transfer the V1 writer. Contract-version 2 prevents stale pre-upgrade verification from being reused.
- The existing Trading Operations UI now distinguishes signed read-only market observations and source-tested exit rules from FULL V1 STRATEGY/AI/EXIT PARITY (still UNVERIFIED).
- Added source comparison, missing-proof, spread/staleness and protective-exit boundary tests; kept all real broker order writers with V1.

## v1.3.45 ? V2 protective exits are independent of entry-only AI policy (2026-11-22)

- Fixed the shared autonomous V2 live scanner so the REQUIRED AI entry policy is checked only for BUY candidates. Validated risk-reducing SELL candidates can proceed without an entry model when AI mode is OFF, while still requiring an authenticated account, authorized writer proof, exact V1 exit/cooldown parity, validated broker-executable quote, risk limits, account inventory and original-order reconciliation.
- New-entry BUYs remain blocked unless the signed account policy explicitly requires validated AI and the reviewer is available. Unknown daily loss, unsettled funds, unverified holdings, stale quotes, missing V1/V2 ownership or AI/exit parity continue to fail closed.
- Added regression cases demonstrating a broker-mock validated protective exit with AI OFF and rejection of a new entry with AI OFF. No brokerage order was submitted and V1 account authorization is unchanged.

## v1.3.44 ? Supervised read-only V2 broker migration coordinator (2026-11-22)

- Added an independently supervised V2 migration heartbeat for Schwab, Webull, and Robinhood in the existing TrueNAS application. The child observes signed preflight freshness, all fifteen broker launch gates, V1 worker heartbeat recency, and cutover blockers, without receiving broker credentials or touching broker order APIs.
- The coordinator is safely restarted on failure, stopped during application unconfiguration or shutdown, and writes only owner-private redacted V2 status. Its heartbeat cannot grant V2 order authority; V1 retains all existing account locks and permissions.
- Authenticated Trading Operations distinguishes supervised **read-only standby** from a registered V2 live order writer, and reports stale/offline supervisor state instead of treating a running container as proof of migration.
- Added fail-closed unit and UI tests for no account-authority transfer, worker-telemetry observation, private journal boundaries and stale/tampered status. Full V1/V2 parity and account-specific funding/session/handoff remain separate unverified launch gates.

## v1.3.43 ? Signed Schwab account migration preflight without dual OAuth writers (2026-11-21)

- Added a read-only signed Schwab V2 preflight invoked periodically using the already-authenticated V1 Schwab worker client; it does not create a second token refresher, broker POST, or live order writer. The probe checks independently signed account/holdings/cash, complete bounded order history, local journal matching, explicit settled-cash evidence, current market hours, and signed fresh executable quotes.
- Published owner-only redacted Schwab migration evidence and connected source-specific launch acceptance checks to the existing Trading Operations view. The UI now prioritizes the V2 first blocker rather than an unrelated legacy readiness reason.
- Historical order discrepancies, pending orders, absent settled funding, closed market sessions, stale quotes and missing permissions remain fail-closed; no migration automatically stops V1 or grants V2 order authority.
- Added nine Python Schwab preflight regression tests plus JavaScript UI contract checks, included in GitHub CI, with no new app or broker credentials.

## v1.3.42 - Fresh signed Webull settlement contract after upgrade (2026-11-21)

- Versioned the read-only signed Webull migration preflight settlement contract so upgraded workers cannot treat a cached pre-upgrade report as current validation evidence.
- Both the status reader and broker launch gate fail closed on old report versions. A newly supervised authenticated GET-only probe refreshes the evidence without an order POST, account arming or V1 writer handoff.
- Added regression tests for stale-but-timestamp-fresh prior-schema reports, typed contract regeneration and blocked live authority. The same signed settled-funding and inventory safeguards from v1.3.41 remain in force.

## v1.3.41 - Signed Webull settled USD funding gate (2026-11-21)

- Added read-only, strict Webull USD settled-cash evidence requiring one signed USD balance record and explicit settled, held, and frozen fields. Missing or contradictory fields, margin usage or cash restrictions remain unverified instead of converting buying power into settled cash.
- V2 Webull BUY sizing is additionally capped by independently signed spendable settled cash, never total cash alone. Existing holdings and sell authorization still require broker and managed-inventory proof; this is not an automatic account handoff.
- Exposed authenticated, redacted settled-funding and external-holdings preflight status in Trading Operations. The V2 launch checker can mark this single Webull settlement prerequisite verified only from a fresh signed report while continuing to block absent session, V1 worker stop, parity, supervisor, writer transfer and broker order acceptance.
- Added malformed, missing reserve, duplicate USD, used-margin and positive settled-funding regression tests. V1 live trading and all broker-writer ownership remain unchanged.

## v1.3.40 - Webull signed position reconciliation and honest V2 migration status (2026-11-21)

- Webull V2 signed read-only preflight now checks every broker-held equity position for unambiguous symbol, nonnegative whole-share quantity, unsupported/short positions and duplicate symbols, then verifies bot-owned net fill inventory against the signed holdings after checking historical signed receipts.
- Contradictory or insufficient signed positions, local histories, or broker order details block cutover. Externally held positions are observed but never adopted as bot inventory; funding, market-session and exclusive-writer handoff remain mandatory independent gates.
- Trading Operations now distinguishes verified read-only signed V1 order history from actual V2 live-order acceptance, without marking any broker live or changing any account ownership.
- Added regression cases for fractional holdings, inventory discrepancy and staged signed-history handling; original TrueNAS state and V1 execution remain unchanged.

## v1.3.39 — Shared V2 live scan and order lifecycle with signed closed candles (2026-11-21)

- Implemented an account-scoped autonomous V2 cycle for all three signed broker adapter types. The same typed stock 3/5 and crypto 4/8 completed-candle crossover controllers feed validated signed executable broker quotes into SharedAIReviewer, the shared deterministic account RiskPolicy, durable SQLite intent and broker receipt reconciliation through LivePipeline.
- A cycle MUST verify exact V2 account-writer generation and an independently current WriterHandoff, including the unmodified Schwab raw account identity, BEFORE creating a live V2 journal or scanning for an order. A second mandatory V1-to-V2 strategy/exit/cooldown/managed-inventory parity provider is fail-closed by default. Signed broker and V1+V2 daily realized loss is required explicitly; the engine cannot silently default it to zero.
- Existing unresolved V2 orders are looked up by original signed broker client/order ID before another candidate; no duplicate POST, no cached quote as execution evidence. A held, validated protective SELL gets priority and does not wait on entry-only AI; BUY still requires a fresh matching typed Ollama PASS when policy requires it, plus broker cash/session/limits.
- Added strict, genuine completed signed Schwab/Webull 5-minute candle sources using original authenticated broker SDK reads and an independent Coinbase minute-bar journal sourced from actual observed public ticker samples for BTC/ETH. No fabricated missing bars, partial-market candles or public data masquerading as broker order quotes.
- Added offline end-to-end autonomous live-scan simulation tests for exclusive V2 ownership, source identity/gaps/staleness, daily loss, invalid AI, verified exits, immutable duplicate order prevention and mandatory V1 parity; signed market-candle tests guard each provider.
- The V2 live autonomous worker is now a tested source component but NOT supervised as a production order writer. V1 account history adoption, full brokerage funding/exit strategy parity, broker market session and a stopped V1 worker with exact atomic ownership transfer are still mandatory before any real cutover. No real V2 orders were placed; V1 broker ownership has not changed.

## v1.3.38 — Native signed V2 Schwab + Webull stock adapters and broker-backed position accounting (2026-11-21)

- Added full canonical live-adapter implementations for Schwab stock and Webull stock using the original signed SDK/account integrations, while retaining their account-specific V1 cash/margin restrictions, broker market sessions, signed live quote timestamps, whole shares, stock-cent price increments, account risk limits, deterministic receipt IDs where available, pre-order existing open-order checks and broker-specific stock previews.
- Schwab V2 journal uses a privacy-preserving canonical alias while the V2 POST lock uses the EXACT raw Schwab account hash locked by V1; alias file locks cannot bypass the original. Both adapters remain unregistered in the production order supervisor pending independently signed account state and actual V1 stop/transfer.
- V2 risk quantizes executable limit prices using the account's signed price increment, not universal 8-decimal crypto precision. Deterministic, risk-reducing exits are independent of entry AI availability while exit count, held-inventory, session and broker restrictions still apply.
- Added read-only canonical V2 SQLite broker-fill position projection, including immutable intent hashes, cumulative partial fill accounting, canceled-partial fills, fee-adjusted weighted cost, and realized net P&L. Uncertain orders cannot be represented as completed fills, and no external holdings are implicitly declared bot owned.
- Completed offline broker interface and LivePipeline tests covering signed Webull stock accepted mock order / signed GET fill / event-store reconciliation / no duplicate POST, broker rejection, account ownership, unknown fills and raw Schwab writer fencing.
- No real V2 broker POST, operator cutover or V1 worker replacement has been made. Production launch still requires authenticated signed funding/holdings/order and market-session evidence, full autonomous strategy/AI/exit/cooldown parity, account-scoped supervisor handoff and live broker acceptance, and a privileged TrueNAS broker inspection channel.

## v1.3.37 — Supervised signed GET-only V2 Robinhood order recovery (2026-11-21)

- Added an isolated Robinhood V2 order reconciler that is invoked by the existing unified supervisor only if a real canonical V2 order journal already exists and the configured Robinhood connection is present. It uses a two-minute minimum restart interval and hard limits each GET-only batch to six original V2 order intents.
- For every submitted or uncertain V2 intent, validates exact persisted identity/fingerprint and account selection, authenticates the account with signed broker GET, then uses the existing strict V2 receipt validator and transactional SQLite state machine to reconcile broker order statuses and fills. Missing broker orders, incomplete fee evidence, wrong accounts, tampered intents or API failures remain unresolved; no order is retried.
- Original intents that were never submitted are NOT sent or automatically promoted. The recovery worker contains no broker order-write operation, does not activate V2 live order authority, and cannot overwrite or replace the V1 broker order journal.
- Exposes a bounded redacted recovery status on the existing authenticated Trading Operations screen, including checked receipts, reconciled terminals and remaining pending intents. Production V2 order activation remains blocked until independent funding/session/AI/exit parity and exclusive single-writer handoff checks are accepted.
- Added eight offline signed broker reconciliation tests including signed completed fill, unknown result, duplicate retry suppression, wrong or ambiguous account, incomplete fee, unchanged pre-submit intent and cryptographic fingerprint tamper detection. JavaScript UI contracts protect worker lifecycle and no-POST behavior.
- V1 autonomous broker workers, financial records, risk settings and order ownership remain unchanged.

## v1.3.36 — Broker-by-broker live V2 launch acceptance gates (2026-11-21)

- Added a read-only, redacted launch acceptance matrix across the three live brokers, distinguishing signed account auth, holdings, order history, pending intents, tradable symbols, market quotes, saved V1 risk, settled funding, market-session entitlement, V1 AI/exit parity, V1 worker shutdown, V2 executor startup/reconciliation, exclusive ownership and actual broker acceptance.
- Rejects stale, wrongly scoped, malformed or world-readable signed probe files. Signed buying power and a valid bid/ask never masquerade as settled funds, session authorization or production order acceptance.
- The authenticated existing Trading Operations dashboard displays each broker's complete acceptance blockers in collapsible detail without exposing account IDs, credentials or broker balances. No extra dashboards or duplicated account navigation were introduced.
- No live V2 orders are enabled. The V2 implementation currently has no complete supervised live strategy/exit/reconciliation worker, and direct privileged production-account inspection was blocked by execution-tool policy. Existing V1 workers and journal ownership remain unchanged until true acceptance is possible.
- Added fail-closed tests for source identity, age, immutable private data, numeric order counts, Webull unnormalized positions and incomplete handoff gates.

## v1.3.35 — Robinhood V2 signed broker valuation of all held inventory (2026-11-21)

- Removed an unnecessary independent Coinbase last-trade requirement when pricing EXISTING signed Robinhood holdings for gross risk exposure. The signed Robinhood broker's actual bid/ask and reported timestamp must be validated for every nonzero holding, including assets not tracked by the BTC/ETH Coinbase signal feed.
- The holdings mark is read-only and cannot become an executable trading quote or a signal. A missing, stale, crossed or excessively wide broker quote still fails the entire account exposure check closed; no holding is silently treated as $0. All holdings count toward capital exposure; managed sellable inventory remains separately derived from verified BOT lots.
- Strict broker quote timestamps are needed for conservative inventory valuation; signed API responses lacking them are explicitly rejected for risk sizing. Entries and exits still require the separate signed broker + time-stamped independent trade crosscheck and exclusive V1/V2 account-writer handoff.
- New no-network tests cover valid signed marks of a non-Coinbase-held asset, stale alt-asset price blocking, and no broker order writes. Previous v1.3.34 Robinhood quote-staleness and duplicate-writer tests remain intact. V1 live execution, broker credentials, risk limits and financial journals are unchanged.

## v1.3.34 — Live Robinhood signed and Coinbase quote sequencing correction (2026-11-21)

- Inspected the actual signed Robinhood V2 BTC-USD quote in production using GET-only access. The response contains one matching symbol with bid, ask and a broker-reported timestamp, and a separate fresh Coinbase public ticker passed dual-source cross-check (the signed GET took ~1.2 seconds). No live orders were sent during diagnosis.
- Corrected the V2 read-only migration probe to request the independent Coinbase trade BEFORE the signed Robinhood bid/ask, eliminating avoidable post-quote staleness when a public GET is slow. The same source order is applied to the Robinhood V2 adapter. Provider bid/ask remain the only source for broker order price checks.
- If the signed broker response contains a malformed, stale or future timestamp, the migration probe and dual-source validator reject it rather than replacing it with a public timestamp. Valid signed timestamps and independently timed LAST cross-checks are tracked separately.
- Persist redacted, bounded per-symbol quote failure codes for BTC and ETH and display them in existing Trading Operations diagnostics; no account identifiers, raw prices, secrets, or provider errors are exposed.
- Expanded offline tests verify public-first request sequencing, signed timestamp freshness and non-bypass, missing public feeds, strict cross-market price agreement, and no V2 order authority.
- V2 live writer handoff remains disabled pending signed funding/session/holdings acceptance, broker-specific strategy/risk parity, V1 writer retirement and integrated execution lifecycle. V1 workers and original order journals are unchanged.

## v1.3.33 — Conservative account-specific V1-to-V2 risk mapping (2026-11-21)

- Added a pure, private-source V1 risk policy translator for Schwab, Webull and Robinhood that maps saved USD maximum order, daily loss, open positions, per-asset percentages, strategy capital, allocation cash reserve and entry/exit counts into a strictly conservative V2 RiskPolicy preview only after receiving an explicitly verified broker Account.
- Robinhood limits derive single-asset dollar exposure from saved total-exposure percentage instead of incorrectly applying it to equity. Webull applies additional 25% cash and equity allocation ceilings. Schwab maintains the selected strategy capital, cash allocation and explicit daily entry/exit ceilings; unsupported saved schemas or missing Robinhood cooldown/exit risk controls fail closed.
- No view or source file authorizes live V2 orders: authenticated cutover diagnostics show numeric mapping state and explicitly separate still-unmapped broker market/session/settlement, V1 AI/exit strategy, order reconciliation and exclusive-writer handoff requirements. No live broker credentials, orders or financial journals are touched.
- Added 8 offline Python risk-source/limits tests and a JavaScript account-risk diagnostics contract. Existing V1 workers, broker per-account controls and full historical order data remain unchanged.

## v1.3.32 — Supervised Webull read-only migration checks in the existing app (2026-11-21)

- Started a bounded, signed read-only Webull migration-preflight child under the EXISTING unified runtime whenever the original Webull connection is configured. It runs account/position/balance/open-order and bounded historical-fill GET checks, with 15-minute restart pacing and a 20-minute read-only evidence TTL.
- The existing authenticated Trading Operations Webull readiness control now has automatic status evidence even without user interaction. Signed GET checks never place/cancel orders, never arm Webull, never create a separate application or overwrite the original V1 SQLite journal.
- Added worker lifecycle handling for disable/error/shutdown paths, bounded private cached status, source and session blocker reporting. No V2 live writer is started; V1 broker order ownership remains unchanged.
- Added automated source and private status tests proving the supervisor has a GET-only preflight and stale evidence cannot authorize any order.

## v1.3.31 — Robinhood V2 real-market schema, cross-venue quote checks and durable writer transfer primitive (2026-11-21)

- Corrected a structural mismatch against Robinhood Crypto's official V2 best-bid/ask schema: the signed broker endpoint provides bid and ask but no native venue timestamp or last trade. The read-only preflight now checks exact signed symbol/bid/ask, a bounded real HTTP request interval, separately observed/timestamped Coinbase BTC/ETH last trades and strict cross-source price agreement. It does NOT pretend Coinbase timestamps are Robinhood timestamps, turn a Coinbase price into a broker order price or infer permission to submit live orders.
- Added an optional dual-source quote path to the V2 Robinhood adapter for supported symbols, preserving original signed-native timestamp behavior where available. Account exposure conservatively values supported holdings at broker ASK; unsupported/unverified holdings fail closed rather than being dropped. Strategy/risk snapshots carry explicit 'robinhood_dual_attested' source identity distinct from Robinhood-only quotes.
- Introduced atomic, account-scoped V1↔V2 order-writer transfer with private hashed-account lease records, generation fencing, exclusive locks, durable atomic file replacement and proof expiration. A transfer requires independent fresh operator, old-worker-stopped, broker order, funding, positions, session, risk and replacement-worker attestations. The primitive is **not exposed via HTTP and is never called automatically**.
- The existing authenticated Trading Operations page now distinguishes signed Robinhood native timestamps from independently timed Coinbase trade crosschecks, and continues showing no V2 live authority. No live V2 broker POST was sent, V1 order writers remain active, and financial journals were preserved.
- Unit tests cover real Robinhood V2 three-field responses, quote divergence, signed request timing, missing/foreign positions, existing exclusive writer-gate rejection and fencing/rollback with exact proof generation. Actual signed broker session/settled-funding and live cutover remain not yet verified.

## v1.3.30 — Merge Robinhood signed execution-precision migration checks (2026-11-21)

- Consolidated previously separate Robinhood V2 migration work into the main feature branch, preserving the original legacy-order execution reconciliation, live adapter and redacted cutover status.
- Validates signed Robinhood trading-pair asset increments, minimum notional and maximum size with conservative canonical-safe rounding. Rejects unsupported sub-canonical increments instead of inventing quantity precision; keeps provider limits distinct from saved application risk budgets.
- Added strict signed-holdings/position precision tests and signed provider increment behavior. Historical fills, broker order IDs, prices and fees continue to require exact evidence; no live V2 order submission is enabled.
- Preserves the V1 Schwab, Webull and Robinhood order writers, broker token data, limits and persistent journals. Source regression: 846 Python tests (845 passed; 1 skipped) before GitHub CI. Real V2 live cutover still requires signed funding, session, position and one-writer handoff validation.

## v1.3.29 — Preflight disarmed accounts safely and cap signed Webull historical GETs (2026-11-21)

- A previously selected Webull broker account can now be checked with authenticated, READ-ONLY broker GETs even when the existing V1 trading flag is disarmed. It remains explicitly NOT cutover ready and is never automatically armed. No selected account still blocks the check.
- Limit each interactive Webull preflight to eight signed historical fill-detail GETs; journals requiring pagination are explicitly blocked instead of saturating the shared SDK rate limit or freezing the dashboard. Existing V1 order histories are left untouched.
- Expose the old operator armed state in the cached authenticated V2 status without account identifiers, token values or broker balances. Additional tests verify disarmed observations and zero excessive broker calls.
- Preserves all V1 workers, broker writer locks and financial history. V2 live brokerage order authority remains OFF until independent signed position/settlement/session evidence and exclusive V1-to-V2 writer handoff are proven.

## v1.3.28 — Webull V2 signed receipt adapter and authenticated read-only cutover preflight (2026-11-21)

- Added a stable, account-scoped Webull v3 32-hex client order ID normalizer and exact signed order-detail reader, translating broker accepted, partially filled, filled, canceled and rejected states into canonical V2 receipt records. Unknown status, mismatched ID, missing signed price/fee, invalid timestamps and partial fills remain unreconciled; there is **no V2 Webull broker POST authority**.
- New Webull preflight confirms explicitly selected V1 account policy, authenticated account/balance/positions/open-order responses, zero open broker orders and equality of V1 locally stored historical fill economics to Webull signed order details. It never infers settled cash, full position reconciliation, a verified trading session or a single-writer handoff.
- Added an authenticated and CSRF-protected read-only Webull migration check button in the existing Trading Operations panel. GET returns a bounded redacted status, POST performs read-only signed Webull account/market diagnostics with a short cache to avoid repeated rate-limited calls. It never arms V2 live execution and does not change any V1 accounts, orders, credentials or risk settings.
- Added 19 offline signed-receipt/preflight Python tests and three JavaScript route/UI authorization tests. V2 source remains live-order disabled while Schwab, Webull and Robinhood V1 workers retain ownership. No test submits a real broker order.
- Remaining live cutover gates: complete signed broker holdings/settled-cash/market-session verification, V1 writer retirement for the chosen account, V2-only ownership generation, independent broker order lifecycle acceptance and authenticated browser verification.

## v1.3.27 — Exact signed historical Robinhood fill reconciliation and migration evidence (2026-11-21)

- Corrected the first broker-authenticated V2 migration-blocker after v1.3.26: V1 historical Robinhood fills can contain precise fractional quantities and a broker-derived weighted execution price rather than a provider average_price. The signed V2 read-only migration probe now uses V1's existing OrderJournal._fill_details normalization for actual signed executions (no invented fill), then compares finite signed quantities, prices and fees to each recorded local V1 fill without altering financial history.
- Individual invalid/missing signed source values, quantity differences, price differences, and unverified/different fees are distinct hard-blocking reason codes, never interpreted as successful fills. The Operations V2 cutover panel presents only redacted first failure and count of historical fills cross-checked (no asset symbols, client IDs, account numbers or prices).
- Regression coverage tests high-precision historical fills, signed multi-execution weighted price fallback, missing fee rejection, wrong quantity/price rejection and old journal preservation. Broker-authorized signed GETs remain read-only; no V2 live writer is spawned, no V1 worker is paused, no V2 account ownership transfer or real-money trade testing has been authorized.
- More work remains: signed historical and current bot inventory equality, market executable quotes, session and settled funding proof, supervised exclusive single-writer transfer, and broker-accepted/fill reconciliation before one live account can be migrated.

## v1.3.26 — Signed Robinhood high-precision holdings normalization (2026-11-21)

- Fixed the V2 signed Robinhood migration probe's genuine production holdings-quantity failure: crypto holdings can report valid decimals with more than 12 fractional places, including zero values such as 0E-18. Added an explicit READ-ONLY holdings normalizer accepting finite nonnegative Decimal, integer or string quantities through 24 fractional places; rejecting nonfinite, negative, float/boolean, missing, unreasonably large or absurdly precise values. Canonical order, broker fill and fee precision limits remain unchanged.
- V2 Robinhood signed account observation reuses the same high-precision holdings parser, counts every external holding toward account market exposure (never as automatically sellable bot inventory), rounds external exposure UP to the nearest cent and account equity DOWN to the nearest cent before passing values into the canonical risk pipeline. New orders still follow exact pair asset increments, minimums, quote time, funding and signed reconciliation.
- Refined private, signed read-only migration diagnostics to surface a bounded reason code when holdings quantity parsing fails; no account numbers, assets, prices, holdings, credentials or broker signing material are published in the Operations preflight.
- Added cases for legitimate 18-decimal holdings, 0E-18, very small valid external exposure and invalid precision or types. The V1 and V2 per-account single-writer locks introduced in v1.3.25 remain intact. No live broker cutover, V1 pause, order submission or guard bypass is part of this change.
- Production broker order history, holdings, exact session, settlement and writer handoff still require authenticated acceptance evidence before real V2 live execution is authorized.

## v1.3.25 — Shared account-writer exclusion and signed broker probe diagnostics (2026-11-21)

- Added durable per-broker/per-account cross-process writer ownership guards using protected SHA-256 account-scoped lock files and fcntl/flock. Existing accounts default to V1 ownership. The V1 Schwab, Webull, and Robinhood Crypto order submit paths now hold the same exclusive account lock from persistence of the legacy intent through broker POST and acknowledgement.
- V2's live coordinator now REQUIRES an existing private owner record granting V2 the correct generation and holds that exact lock through the entire signed submission workflow; neither a forged handoff callback nor a missing owner record can authorize V2. No production action to set V2 ownership is available until signed acceptance, account risk, reconciliation and an exclusive V1 stop can all be proven.
- Added targeted no-network tests for same-account locking, V1 default behavior, V2 owner rejection of V1 BUY/SELL, unverified files, symlink/mode protection, race exclusion, and V2 refusal when ownership is not transferred.
- Extended the signed Robinhood migration probe's holdings failure reporting with bounded, non-sensitive reason categories and exception CLASS only. Authenticated status downgrades stale/future probes and never treats cached observations as a current broker authorization. The existing Operations panel displays which signed holdings check failed.
- Live V1 trading permissions and policy values remain unchanged; no new V2 live broker writer is spawned and no real test orders were sent. Robinhood production migration remains gated by signed holdings and historical fill verification, broker funding/session proof and a safe V1-to-V2 worker handoff. Schwab and Webull real V2 broker execution cutovers are not complete.

## v1.3.24 — V2 live-order coordinator staging, Robinhood signed adapter and production migration probe (2026-11-21)

- Added a distinct fail-closed V2 **live execution coordinator** that shares the canonical paper receipt/event state machine but requires a fresh operator-authorized, single-writer, account-specific handoff, signed executable market data, verified funding and broker-session proof before any real submission. It cannot accept the simulated broker or be activated by importing this module.
- Added a Robinhood V2 adapter using the existing signed official Crypto API: broker-selected account, exact-UUID deterministic client intent mapping, full signed order-history lookup, per-pair minimum/increment/maximum, quote source timestamps, and strict realized fill quantity/price/fee evidence; missing data or changed IDs cannot be guessed. External holdings affect exposure but are excluded from automatically sellable BOT inventory until independently attributed to actual fills.
- Enforced one unresolved V2 account intent inside the same SQLite BEGIN IMMEDIATE transaction, eliminating a cross-worker duplicate account-order race. Cash-funded crypto quantity now rounds down to broker-verified fractional increments before persistence, not a universal eight-decimal assumption.
- Added a 15-minute, supervised, **read-only** signed Robinhood migration probe (no POST or cancel) to inspect real account permissions, holdings, selected pair constraints, authoritative full order history, local vs signed bot fills, open orders and signed quote timestamps. Its credential-free report is displayed inside the existing authenticated Trading Operations preflight; a running worker or local FILLED status never enables V2 by itself.
- This milestone does NOT launch any V2 live broker-order worker, pause existing V1 order writers, or grant V2 live authorization. Schwab and Webull V2 write adapters and broker-certified handoff remain incomplete. Signed brokerage acceptance and real fills are intentionally not simulated as production facts.
- New no-network regression coverage exercises handoff revocation/generation changes, timeout-after-acceptance and duplicate prevention, historical signed receipts, partial fills/cancel economics, broker cap/increment rechecks, external vs bot inventory and source quote stamps. Full Python and JS regression tests and GitHub CI required before deployment.

## v1.3.23 — Source-faithful legacy journal evidence, market-session visibility and four-workspace navigation parity (2026-11-21)

- Added a strictly read-only, file-permission-validated legacy V1 order evidence adapter for Webull SQLite and Robinhood Crypto JSON. It summarizes bounded account counts, local terminal fills, unresolved/partial order intents, missing fill prices/fees/broker IDs and invalid journal/source evidence without reading API keys, initializing a journal, placing an order or treating a local "FILLED" record as signed broker confirmation.
- The existing authenticated Trading Operations live cutover panel now surfaces those local records and explicitly blocks V2 cutover for unresolved intents, unsafe/missing journals or incomplete fill details. Existing V1 worker status and broker-historical verification remain separate, and V2 live broker order authority is still disabled.
- Added US-equity market-session *window* evidence for Schwab and Webull with Eastern Time DST/weekday/weekend handling. Even within 09:30–16:00 ET the result is calendar/holiday-unverified and never claims a broker is open or executable; Robinhood crypto similarly remains broker-session unverified.
- Reused each of the original Schwab, Webull, Robinhood and Paper dashboards to add the same six responsive, clickable local sections in the same order: Overview, Strategy & AI, Risk & Start, Orders, Portfolio, Diagnostics. Portfolio/Diagnostics focus their real existing panels. All prior broker-specific auth, live start/pause, account controls, positions and settings are retained; no fifth dashboard was introduced.
- Added 21 Python broker journal/session regression tests and three JavaScript parity checks. These enforce unsupported broker rejection, state-file absence and permission safety, duplicate IDs, cross-account ambiguity, partial/uncertain orders, fee/price evidence, fixed timezone boundaries and no V2 live authority.
- Source regression results before release: 735 Python tests (734 passed; 1 skipped) and 22 Node test files. Browser-authenticated UI verification and live broker executor acceptance remain outstanding; this release is observational, not a V2 live cutover.

## v1.3.22 — V2 broker-receipt boundary validation and fail-closed partial-fill recovery (2026-11-21)

- Validates all V2 broker execution receipts against the ORIGINAL persisted intent before recording an accepted, partial, filled, canceled or rejected order. A matching idempotency key alone no longer establishes a valid fill: cumulative quantity cannot exceed the authorized quantity, a claimed full fill must match it exactly, marketable average fill price must respect the saved BUY/SELL limit, and a provider cannot silently change the broker order ID or regress an earlier partial fill.
- Adds strict broker-receipt value/status/identifier validation and retains cumulative quantity, actual receipt price and fee evidence when a partially filled order is subsequently canceled or rejected.
- Invalid or inconsistent evidence is persisted as UNKNOWN_REQUIRES_RECONCILIATION (or remains unresolved) and the original order is never blindly resubmitted. A later read-only lookup by the original idempotency key may reconcile it; no new order writer or broker API was introduced.
- New regression tests cover incorrect full fills, overfills, limit violations, invalid state and monetary values, changed broker order identity, decreasing partial fills, cancellation economics, and no re-post after an ambiguous reply. The full 714-test Python suite passed locally with one skipped test prior to GitHub CI.
- Existing V1 Schwab, Webull and Robinhood live order services are unchanged. V2 continues to use only SimulatedBroker for order writes; V2 live authority, broker adapter reconciliation and account cutover remain disabled. No new risk controls are bypassed.
- Next: independently verified broker order/holdings/settled-cash adapters, live market-session validation, account-specific V2 risk mapping and staged single-writer cutovers after broker-safe acceptance.

## v1.3.21 — Durable V2 crypto fee/reward shadow and rolling cost blocker frequencies (2026-11-21)

- Extended the existing private SQLite V2 crypto paper scan journal to persist advisory fee/reward classifications by symbol and one-minute interval, without touching the simulator order journal or opening another brokerage connection. A backward-compatible, owner-only ALTER TABLE migration adds fee_shadow_state to existing V2 scan data without discarding historical records, and the status reader supports legacy journals before their first post-upgrade scan.
- Fee shadow evidence is kept when a later no-signal scan occurs within the same minute, analogous to preserved AI and fill evidence. Source reports that attempt to grant live order authority or change execution are rejected as evidence-unavailable, not treated as valid passes.
- Existing Trading Operations 3h/24h BTC/ETH reports now include the count of verified advisory shadow assessments with sufficient estimated reward to revisit past highs, counterfactual insufficient reward after simulated fees/spread/slippage, spread rejections, and insufficient history. Previously recorded no-signal scans are NOT fabricated into historical fee evaluations; history begins only after this migration captures genuine candidates.
- Full offline source/test coverage preserves original simulated fill sequences even when shadow cost outcomes reject entries. Existing live broker traders, V2 simulation order pipeline, account permissions, risk limits and estimated cost assumptions remain unchanged; no V2 live order authority is enabled.
- Regression tests validate schema migration from the actual old journal layout, preservation of order/signal rows and repeat-scan fee outcomes, malformed or authorizing evidence refusal, rolling read-only 3h counters, legacy read compatibility and no network/trading side effects. This is a measurement milestone, NOT evidence that the suggested fee gate improves real or simulated return.
- Remaining: enough fresh shadow samples for statistically meaningful strategy comparisons, rigorous out-of-sample replay of fees and slippage, market-session and account mapping checks, broker adapter reconciliation, and staged single-writer live cutover.

## v1.3.20 — Crypto fee/reward shadow evidence from existing V2 paper signals (2026-11-21)

- Added a deterministic *advisory-only* crypto fee/reward assessment of V2 BUY candidates. On each genuine completed one-minute SMA cross the shadow evaluator checks price/quote identity, original quote age, a contiguous 21-bar historical lookback, observed public bid/ask spread and an earlier 20-candle resistance level without using future prices.
- The counterfactual estimates buy entry at the present public ask plus the existing V2 simulator's 5bps buy slippage and fee, then estimates sell proceeds if price revisited the *previously observed* resistance, using the current bid/last ratio, 5bps sell slippage and fee. A hypothetical minimum +0.5% net reward and maximum 0.5% public spread are *diagnostic assumptions*, NOT new order restrictions, guaranteed returns or broker-tradable prices.
- V2 reports SHADOW_PASS_PAST_RESISTANCE_ROOM, SHADOW_REJECT_REWARD_AFTER_FEES, SHADOW_REJECT_SPREAD, INSUFFICIENT_HISTORY, or EVIDENCE_UNAVAILABLE for eligible BUY candidates. SELL candidates are EXIT_NOT_GATED. No fee review can veto, size or authorize an order. No direct broker SDKs, new market API calls, OAuth refreshes, or trading permission changes.
- Existing independent V2 crypto paper pipeline still uses CryptoController -> optional AI shadow -> deterministic RiskPolicy(ai_mode=OFF) -> idempotent EventStore -> SimulatedBroker with its **original unchanged candidate and risk decisions**. The new diagnostics are evaluated independently and fail noncritically.
- Trading Operations' existing BTC/ETH paper status now displays the latest fee/reward shadow state and numerical illustrative reward-at-past-resistance where evidence permits, clearly labelled nonexecutable and not a price forecast. No new separate dashboard or live broker control is introduced.
- Added test coverage for meaningful hypothetical upside, targets too small to overcome fees, public-market spread rejection, incomplete/gapped data, stale/mismatched quotes, invalid cost assumptions, and exits excluded from entry gating. An end-to-end offline paper-tape test proves forced SHADOW_REJECT_REWARD_AFTER_FEES cannot change the original simulated fill sequence.
- V2 has not been permitted to submit real broker orders. Existing Robinhood live trade monitoring is handled independently; this feature does not modify Robinhood order logic. Full market-session, canonical broker adapters, settlement/lot accounting and one-writer handoff remain mandatory before any live V2 cutover.

## v1.3.19 — Reconciled V2 simulated realized net profitability (2026-11-21)

- Validated the existing genuine V2 BTC/ETH simulator ledger against all filled orders, virtual-account cash and remaining inventory, using the exact SimulatedBroker weighted-average acquisition cost including purchase fees and sale proceeds after sale fees. No broker SDK calls, new orders, credential reads, or live policy changes.
- Production read-only verification: BTCUSD 6 simulated fills, 3 completed round trips, 0 profitable, fees $0.06, realized net -$0.14; ETHUSD 6 fills, 3 round trips, 0 profitable, fees $0.06, realized net -$0.16. Both accounts have zero remaining inventory and their virtual cash balances reconcile. These are synthetic executed prices with modelled costs, NOT real broker accepted fills or real investment performance.
- Added strictly private, read-only simulated economic reconciliation under the existing authenticated V2 paper status API and the Trading Operations crypto paper section. It displays verified completed round trips, profitable cycles, assumed fees, net realized simulated P/L and any remaining simulated position, or a reconciliation-required state if the ledger cannot be verified.
- Fail-closed verification rejects invalid/tampered funds, mismatched asset/account symbols, malformed or future order timestamps, non-SIM order IDs, cross-account positions, missing simulator accounts, and inaccessible or public/symlinked ledger files. It never turns an unverified ledger into a zero-profit claim.
- Distinguishes ledger-assumed fees from market spread/slippage: no reliable source quote at each simulated fill is persisted, so the additional impact from simulated spread/slippage cannot be separately attributed. A profitable backtest is not claimed.
- Added tests using actual SimulatedBroker submissions for cash/position reconciliation, losing/winning round trips, open holdings, invalid source evidence and no live-order access; bounded UI output is a read-only addition to the existing account workspace.
- Next work: fee-adjusted candidate filtering with reproducible historical replay and shadow baseline comparison, broker market-session checks, canonical per-account risk, broker adapters and staged one-writer handoff before any V2 live authority.

## v1.3.18 — V2 three-hour/24-hour paper scan-to-fill diagnostics (2026-11-21)

- Inspected the real TrueNAS V2 crypto paper scan and simulator ledgers for the previous three hours. Both BTC and ETH scans remained active, AI returned PASS/VETO/UNAVAILABLE evidence, and zero new simulated fills occurred because the existing three-entry daily cap and absence of held inventory blocked new orders. No broker orders were placed by V2.
- Added an authenticated, read-only rolling 3h and 24h diagnostic aggregating persisted scan-minutes, candidate signal-minutes, exact entry/exit block reasons and AI shadow outcomes, with separately verified actual simulator BUY/SELL fill counts and accumulated assumed fees. Never mistake a signal for a fill; missing, malformed or unsafe ledger files report unavailable rather than falsely asserting zero.
- Validated the aggregator against actual production PaperPipeline events, which use state BLOCKED plus candidate side BUY/SELL. Fixed the initial implementation to match this real schema, preserved older canonical status support, and added tests for the regression.
- Updated the existing Trading Operations V2 crypto paper section with rolling 3-hour and 24-hour summaries, including the top why-no-trade risk reasons and counts. This does not add an independent workspace, modify V1 live broker workers or enable V2 order authority.
- Fixed a clock-dependent test that used a dated November 20 candle tape with an ambient 24-hour window; it now reads its fixed tape against its own recorded timestamp, without weakening any production time checks.
- Added tests for timing windows, risk rejection aggregation, source permissions and symlink handling, simulator fill verification, duplicate scan minutes, stale/malformed evidence and zero live-order authority. Source Python suite passed 681 tests (one skipped), before CI and image deployment.
- Remains blocked for live cutover by broker order adapters, reconciled holdings/lots and settled cash, market-session verification, and a staged one-writer-per-broker handoff. Simulated P/L does not establish economic viability.

## v1.3.17 — Fast structured Ollama advisory decisions for V2 stock and crypto shadow (2026-11-21)

- Updated the V2-only Ollama /api/chat transport to send a strict object-schema for {symbol,state,reason}, disable generation of internal reasoning tokens, cap predicted response tokens at 90 and context at 2,048, and keep deterministic zero-temperature selection. This reduces needless inference while retaining the shared typed response/identity checks and existing six-second timeout.
- On the configured production model, a single synthetic no-order Ollama JSON probe with reasoning disabled and constrained output returned a valid state and symbol in approximately 405 ms, compared with prior isolated V2 review timeouts over six seconds. This is a transport benchmark, NOT a validated actual market signal, profitability result, or broker acceptance. Behavior under concurrent V1/V2 load still needs ongoing evidence.
- Stock-shadow and crypto paper Trading Operations diagnostics now display available bounded model latency. Stock shadow records nonsecret model/latency alongside optional advisory PASS/VETO/UNAVAILABLE decisions; no review is allowed to alter live or simulated order authority.
- Existing strict validation still rejects malformed/mismatched model outputs and stale prices/candidates. Failed or slow reviews remain UNAVAILABLE rather than being silently approved; no risk, order, broker credential or model-selection setting was changed.
- Added transport request-shape tests for strict schema, allowed state enum, explicit think=false, bounded context/tokens and the existing HTTP/response-size protections. Ran focused AI/paper/stock tests and full Python/UI regression checks before deployment.

## v1.3.16 — Per-account V2 risk mapping audit and effective V1 budget preview (2026-11-21)

- Added an authenticated read-only V1 risk-budget preview alongside each live broker in the existing V2 Trading Operations cutover panel. It reads private, bounded user-selected V1 risk documents and only freshly verified account observations, and makes no broker SDK calls or writes to V1/V2 risk, journal or token files.
- Schwab: reproduces the current scanner's strategy-capital ceiling (never greater than verified equity), saved order ceiling, position percentage, cash-allocation percentage, actual cash and existing exposure to calculate a preliminary USD upper bound. A legitimate legacy nine-field Schwab document inherits the V1 validator's three-exit fallback, visibly labeled as such rather than silently presented as a saved setting.
- Webull: applies the existing 25% cash and total account exposure gates, saved hard-capped per-order and per-position limits, broker-reported verified entry headroom, and account class; unverified margin cash funding and reconciliation remain explicit blockers.
- Robinhood Crypto: preserves the distinction between broker-reported buying power and unverified cash/equity/positions. A preliminary buying-power ceiling is displayed separately, but no permitted entry budget is asserted without holdings and fee/order-minimum verification.
- All reports state v2_order_authorized=false, ready_to_submit=false and verified_broker_order_limit=false. No canonical live V2 policy is auto-armed or copied from V1. These estimates do not include current executable quotes, broker market sessions, settlement, order minimums, fees or the V1-writer handoff. Broker/source changes or unknown values fail closed.
- Production read-only audit, prior to release: Schwab recorded V1 order ceiling $50 and preliminary observed headroom $34.46; Webull recorded V1 order ceiling $80 and remaining source-authorized entry headroom $0; Robinhood recorded order ceiling $10 but lacks the complete verified equity/holdings required for a safe V2 entry budget. These values are point-in-time diagnostic observations, not trade recommendations or evidence that a broker order would be accepted.
- Regression tests cover correct source formulas and legacy Schwab schema, exposure/cash exhaustion, invalid source magnitudes, Webull hard caps, Robinhood buying power isolation, private file permissions, API authentication, read-only UI reporting and zero live-order authority.
- Still outstanding: mapping remaining source-specific settlement and position-lot rules into canonical V2 RiskPolicy, verified market-session and executable quotes, signed order reconciliation, per-broker V2 execution adapters and staged one-writer live cutover.

## v1.3.15 — Continuous V2 stock shadow signal evaluation, no live authority (2026-11-21)

- Added a supervised, broker-independent READ-ONLY stock-shadow worker for the exact 24-symbol V1 Schwab eligible universe. It runs alongside the current Schwab worker while Schwab live scanning is enabled, with bounded backoff and explicit worker heartbeat. It never authenticates to Schwab, makes no additional broker SDK call, and cannot submit either simulated or live orders.
- V1 Schwab five-minute price-history fetches are now safely teed to a separate private V2 candle recording. The tee preserves the exact V1 return value and catches diagnostic failures so existing V1 stock entry/exit selection, authorization, order journal and risk policy remain unchanged. The already-normalized V1 Schwab quote batch is reused separately, and exchange timestamps and source identity are checked again by the V2 consumer.
- Completed genuine five-minute source candle history is stored privately with the original Schwab timestamps. The V2 StockController receives only verified, sorted, completed contiguous candles; it never fabricates prices, presumes open markets, or treats a point-in-time ticker as a completed OHLC bar. After genuine fresh quotes and candles, a qualified V2 stock signal is recorded with optional bounded non-authoritative Ollama PASS/VETO/UNAVAILABLE evidence. Repeat scans persist one immutable signal observation per stock and candle.
- Added a protected read-only GET /api/v2/stock-shadow, a single structured V2 stock source/status panel in the existing Trading Operations view, and an expandable per-symbol diagnostic list. The report clearly distinguishes unavailable/stale/warming-up/gapped candles, NO_SIGNAL, and stock candidates that still lack broker-order authority.
- Read-only integration tests validate BUY signal/AI evidence, duplicate suppression across restarts, market-session/execution boundaries, stale or malformed quotes, raw candle integrity, non-trading V1 fallback, owner-only artifacts and authenticated API access. Full 664 Python tests (one skip) and all 21 JavaScript test files passed before CI.
- As November 21 is Saturday, source recordings from the new V1 stock history tee have not yet been collected during an open-market session. A deployed worker and weekend SOURCE_UNAVAILABLE status do NOT prove a profitable stock strategy, market-session verification, actual execution, or broker fills. V2 live-account cutover remains disabled; next is fresh Schwab trading-session acceptance, account-specific risk-shadow mapping, and per-broker executor reconciliation.

## v1.3.14 — Reuse existing Schwab scanner quotes for V2 stock observations (2026-11-21)

- Attached a read-only, sanitized stock-quote telemetry write to the already-authorized V1 Schwab scanner's existing get_quotes response. The response is normalized to source-specific stock observations and written atomically with owner-only permissions for V2 MarketDataProvider and the existing cached market status API; no new OAuth session, broker API request, trade action, order adapter, or broker risk behavior is added.
- The write occurs only after the V1 scanner actually receives a quote batch. V2 retains genuine Schwab exchange quote timestamps and rejects stale, crossed, missing bid/ask, wrong-symbol or unverified stock-market data. A current file collection timestamp alone cannot imply current prices, verified trading hours or broker-executable quotes.
- Telemetry write/normalization failures are caught as noncritical; the V1 stock candidate selector continues to evaluate the original unchanged quotes. Account restrictions, settlement, stops, exit priority, duplicate-order prevention and the active real-order writer remain exclusively under the existing V1 Schwab worker.
- Added integration tests for the same quote API response being used once, stock-source normalization, nonexecutable V2 quote contracts, private cache permissions, stale original timestamps and graceful non-trading telemetry failures.
- The preceding V2 cutover preflight remains authenticated, read-only and non-authorizing. With US equity markets closed at the time of this deployment, a genuine *fresh production stock quote* and a V2 stock signal/fill are NOT claimed; next milestone is continuous independent stock paper observation with verified market hours and market-closed behaviour before any per-account broker cutover.

## v1.3.13 — Read-only V2 staged live-account migration preflight (2026-11-21)

- Added a canonical four-account cutover readiness report under existing authenticated GET /api/v2/status. Each broker displays verified authentication/worker state, user-selected V1 permission, market-source freshness, actual private V1 risk-policy fields with their file source, and honest V1 order/reconciliation coverage. V2 does not automatically inherit any live account authorization or limit.
- Schwab reads the private V1 order journal in bounded read-only mode, classifies local unresolved/halted records, and reports pending or unknown order state as a blocker. Webull and Robinhood retain explicit BROKER_RECONCILIATION_UNVERIFIED classifications until signed order reconciliation is implemented in V2; a V1 status cannot establish V2 broker-order acceptance.
- Every live account reports V1 order-writer ownership and an explicit first cutover blocker. All four accounts remain NOT READY for V2 live execution, with no order authority, no automatic handoff, no broker SDK calls, no OAuth refresh, no risk-setting writes, and no new database.
- Existing Trading Operations page now includes a V2 live-account migration preflight within the original V2 panel. Read-only source, V1 limit coverage, local intent resolution, and migration blocker are visible alongside account verification. No extra dashboard or action to arm a V2 order writer is introduced.
- Production pre-release verification confirmed Schwab, Webull and Robinhood authenticated and active in V1, with current Schwab local order journal 19 terminal entries and 0 unresolved. The separate legacy three-week-old trading-live container targeted the same Schwab account, was paused, and had no order records; it was STOPPED without deletion, while the current TrueNAS Auto Trader remained healthy and Schwab worker verified. Old source/config and rollback capability were retained.
- The Schwab broker quote cache remains stale and Webull stock quotes are not independently verified; Robinhood's public crypto feed remains NON-EXECUTABLE. Actual V2 live broker adapters, market session/order minimum verification, full reconciliation, UI parity and staged per-account cutover remain outstanding.
- Regression tests enforce no file writes, no broker-order authority even with connected accounts, per-account V1 risk-source isolation, halted/unresolved journal blocks, auth revocation blocks, and authenticated browser rendering.

## v1.3.12 — One Schwab setup card and resilient OAuth replacement (2026-11-21)

- Restored Broker Connections as a permanent main navigation item directly beneath Account Overview, rather than burying it in the account-specific navigation. Reuses the existing Broker Connections view and existing Schwab adapter; no new dashboard or broker service is created.
- Embedded Schwab OAuth into the same broker card pattern as Robinhood and Webull. The primary button is Connect / Reconnect Schwab, with inline status, an official Schwab sign-in link, optional full callback URL entry when the registered redirect points to 127.0.0.1, a read-only Verify Schwab accounts action, and explicit real-money account activation confirmation. Developer key/secret/callback settings are placed behind an advanced disclosure; saved secrets are never displayed.
- Added authenticated, same-origin, CSRF-protected POST /api/schwab/connect. It automatically selects new authorization or replacement based on the presence of a saved token, without treating a saved/revoked token as evidence of a verified active connection. Existing legacy API paths and /broker-schwab.html remain available for compatibility, but normal users no longer need a separate page.
- A valid pending OAuth sign-in is reused across dashboard session reloads instead of silently overwriting its state. Start a new sign-in explicitly invalidates the old pending state when a code has been used or an authorization fails. Expired and malformed pending state safely create a fresh authorization.
- OAuth session creation and code exchange are serialized to prevent concurrent callbacks and start requests from overwriting each other. Prior private token backups no longer block later verified replacements; each replacement preserves a separate unique 0600 rollback copy. The old token is only replaced after a successful Schwab signed account lookup, and previously selected account access is checked.
- The Schwab dashboard's Reconnect action now opens the Broker Connections view rather than navigating to the old standalone page. The account-overview Schwab tile distinguishes RECONNECT REQUIRED from a merely saved but unverified authorization. Other brokers and all trading/risk settings are unchanged.
- Added mock verified-reconnection tests for returning browser sessions, repeated backups, expired pending flows, explicit restarts, wrong OAuth state, CSRF protection, account-selection risk gate and simulated DOM interactions, including confirmation required before enabling live orders.
- This version DOES NOT bypass Schwab official sign-in, registered callback requirements, actual broker verification, risk limits, per-order safety, or existing reconciliations. Production Schwab OAuth remains user-driven and cannot be completed without the user's official Schwab consent.

## v1.3.11 — Schwab Start Trading correctly identifies revoked OAuth (2026-11-21)

- Fixed the Schwab dashboard and Risk & Start actions that were labeled Start trading while the worker was offline for REAUTH_REQUIRED and silently redirected to generic Broker Connections. The action now clearly says Reconnect Schwab when the backend verifies the rejected refresh-token marker, and navigates only when the user explicitly chooses reconnection to the dedicated Schwab OAuth screen.
- The backend GET /api/live returns a nonsecret auth_state (REAUTH_REQUIRED, AWAITING_WORKER_VERIFICATION, WORKER_VERIFIED, NOT_VERIFIED) and a fixed auth_reason code. The expiry marker is compared with the current token fingerprint without reading or exposing token contents.
- POST /api/live/mode refuses real-money Start while a revoked OAuth marker remains, independently of a recent previously-armed heartbeat. It also does not treat a newly replaced token as worker-verified while the supervisor still reports reauthorization or reconciliation required. Pausing remains accessible while offline.
- If the Schwab worker is offline for a reason other than rejected OAuth, Start shows the actual worker/readiness block in place without redirecting or changing account risk/permission settings.
- Both existing Schwab workspace and Risk & Start panels display the same action label and descriptive status; after a successful broker reconnection and worker verification, the buttons return to Start trading. Confirmation for enabling real-money trading is unchanged.
- Added synthetic revoked-token server tests, protected state comparison, CSRF and origin cases, pause and recovery behavior; added DOM-executed Node tests of both button states and their intended navigation.
- Schwab must still complete the official user-driven OAuth consent and verified account lookup; we cannot silently replace a rejected token or enable real orders on the user's behalf. The other brokers, paper engine, V2 safeguards, AI and order journals are unchanged.

## v1.3.10 — Durable V2 crypto paper scan economics and model timeout diagnostics (2026-11-21)

- Added a private, standalone, bounded 30-day SQLite V2 paper scan observation ledger for BTCUSD and ETHUSD, keyed by symbol and UTC minute. Repeated 30-second polls do not duplicate signal/fill minutes; a stronger confirmed simulated-fill outcome is not replaced by a subsequent no-signal poll.
- Existing authenticated GET /api/v2/paper-fresh now provides read-only 24-hour scan scorecards for each account: sampled minutes, actual eligible-signal minutes, no-signal coverage, data errors, simulated-fill minutes, shadow AI PASS/VETO/UNAVAILABLE counts, last paper observation and synthetic marked-to-market P/L and peak-to-trough drawdown. P/L includes simulation cash/positions and the simulator's configured assumed fees/slippage. No live-broker result, actual fee or strategy profitability is implied.
- The scorecard is displayed below the current BTC/ETH paper worker status inside the existing Trading Operations view, with explicit labels for its synthetic nature and missing performance evidence.
- Shared typed AI reviewer distinguishes socket/transport TimeoutError as MODEL_TIMEOUT instead of generic AI_UNAVAILABLE. Production read-only probe confirmed configured Ollama HTTP endpoints respond quickly and the chosen model is listed, but an isolated candidate review exceeded the six-second budget. No model PASS/VETO has been confirmed from an actual production signal; that remains a validation gap.
- Added tests for read-only status, owner-only SQLite permissions, independent accounts, scorecard aggregation, restart/minute idempotency, preserved strongest fill state, time windows, invalid paper values/symlinks, existing API auth, browser contract and simulated-only isolation.
- The V2 live broker writer remains OFF. Existing paper and live broker processes, live journals, saved risk settings, credentials, OAuth, order minimums, and safeguards are unchanged. Next milestones: qualified real-signal shadow evidence, fee-aware replay benchmarking, stock paper feed and account-specific V2 UI/live cutover.

## v1.3.9 — Strict AI shadow decision capture for V2 public crypto paper (2026-11-21)

- Connected the existing shared V2 AI reviewer and bounded Ollama JSON transport to qualified public crypto paper candidates as a NON-AUTHORITATIVE shadow assessment. The operator-configured Ollama URL/model are reused; there is no new account credential, untrusted external endpoint, live adapter or broker-side order request.
- AI responses are symbol-bound and schema-validated with a 6-second transport budget, TTL and timestamp checks; PASS, VETO, UNAVAILABLE, NOT_CONFIGURED and NOT_INVOKED are reported accurately. Malformed/wrong-symbol/expired responses and connection failures never count as approval.
- Paper orders still use the tested no-AI baseline through deterministic risk, EventStore and SimulatedBroker. Even a shadow VETO cannot submit, reject or alter a simulated order; model response cannot bypass authentication, broker restrictions, exposure, cash or duplicate-intent controls.
- Added a nonsecret model/decision/reason/latency/expiry read model and source-safe text-only AI shadow evidence in the existing V2 Trading Operations view; no new dashboard or direct broker-trading UI.
- Added tests for model response validation, VETO isolation, wrong symbol, unavailable/timeout behavior and no model/network fallback. Live runtime verification of actual Ollama responses requires a fresh qualified signal and a working configured model; no AI-controlled live order has been placed.
- Still outstanding: broker-independent stock paper market data, account-specific AI policy controls, V2 live adapter/reconciliation integration, four-dashboard parity, quantitative replay benchmarking and staged live cutover.

## v1.3.8 — Independent continuously supervised V2 public crypto paper worker (2026-11-21)

- Added a production-contained Coinbase Exchange public ticker adapter for BTC-USD and ETH-USD, validating genuine exchange timestamps, bid/ask, last trade, spread and quote freshness. Explicit fixed HTTPS endpoint allowlist; no broker OAuth, tokens or order placement.
- Separate V2 paper worker samples the public ticker every 30 seconds, persisting the last real observed trade per UTC minute. Only completed, contiguous one-minute observations can produce V2 CryptoController candidates; no historical candle guessing, forward-fill, or fabricated trading signals.
- The shared deterministic V2 paper pipeline independently validates account, simulated cash/exposure, spread, signal freshness and entry/exit limits, persists unique order intents in its SQLite WAL journal, and submits only to SimulatedBroker. Independent BTC and ETH virtual cash accounts start at $1,000 each, never reset on worker restart; fees/slippage are simulated and clearly labeled.
- The existing unified runtime supervises V2 fresh-paper alongside V1 without sharing brokers. It runs only when the operator's existing Paper Trading setting is enabled, stops when disabled, and backs off after a crash; no V2 live-order authority is possible.
- New authenticated read-only GET /api/v2/paper-fresh and Operations detail show warm-up/closed candles, heartbeat freshness, source-specific errors, real scan signals, simulated holdings/equity, and durable order counts. AI mode remains OFF for this no-AI baseline; live broker order status is untouched.
- Integration tests cover malformed/stale/crossed/public market data, delayed fetch clock, unique accounts and journals, completed-bar warm-up, simulated signal/fill and restart idempotency, API authentication, UI and supervisor gating. TrueNAS real public-feed probe returns genuine observations and WARMING_UP without live orders.
- Still outstanding: wired shared AI reviewer, stock-independent public feed, real candle/replay performance validation, V2 broker execution adapters, all-four account page parity and staged live cutover. Live broker quote and actual broker fill validation have NOT been established by Coinbase paper scans.

## v1.3.7 — Authenticated, broker-independent recorded V2 paper replay (2026-11-21)

- Added an operator-triggered historical replay inside the existing Trading Operations V2 detail, with a list of explicitly supported recorded instruments, available closed candle counts, last replay report and actual simulated order/fill numbers.
- Runs the V2 stock/crypto strategy controllers through the same deterministic risk, idempotent intent/EventStore journal and SimulatedBroker pathway. Historical source is the existing paper collector's completed-bar CSV, not Schwab OAuth, a broker quote or a made-up current price.
- Synthetic bid/ask spreads, fees and slippage are declared in the report (10/5/5 bps defaults). AI is explicitly OFF for the no-AI baseline; decisions and synthetic fills cannot be construed as live profitability or verified executable broker quotes.
- A source-hash/strategy-version run identifier persists each replay's independent SQLite broker/order journal and private 0600 JSON report under state/v2/recorded_replays, leaving all Schwab/Webull/Robinhood/V1 Paper order journals untouched. Identical recordings return the same report without duplicate events.
- Added authenticated GET /api/v2/replay and CSRF/Origin-protected POST /api/v2/replay/run. Input accepts only a predefined recorded instrument; data size, bar count, file type, directory permissions and concurrent writes are bounded; no live broker order-writing code is reachable.
- Added integration, durability, input validation, symlink, unknown symbol, auth and UI regression tests. The general V2 live cutover remains disabled. Next: independent fresh candle provider, real-market replay, account-specific AI/shadow comparison, full dashboard parity, and broker write-adapter integration.

## v1.3.6 — Read-only V2 why-no-trade diagnostics (2026-11-21)

- Added a typed, bounded, broker-agnostic diagnostic reducer for Schwab, Webull, Robinhood Crypto and Paper accounts. Each account reports verified vs unknown authentication, worker, account observation, operator permission, read-only market data, strategy signal, AI, risk and order reconciliation gates.
- Shows the first known blocker and specific user action in the EXISTING collapsed Trading operations account-readiness panel; no new dashboard, account permissions, broker SDK calls or order endpoints were introduced.
- Explicitly refuses to call a broker ONLINE or an external public Coinbase quote sufficient evidence for live V2 market execution; never labels a missing V2 scan NO_SIGNAL, and never confuses V1 configured permission with actual working broker readiness.
- Added seven reducer regressions, API integration coverage through existing suites, and browser UI contract checks. V2 live order authority and feature flag remain OFF; legacy V1 broker workers, risk limits, journals, and credentials remain unchanged.
- A connected account still requires genuine V2 strategy/AI/risk/order reconciliation, real market data, and account-specific broker write-adapter validation before live cutover. Schwab remains REAUTH_REQUIRED until authorized OAuth reconnection.

## v1.3.5 — Portable post-deployment UI regression path (2026-11-21)

- Corrected a Schwab Risk & Start test fixture to locate existing web assets both from a repository checkout and the flattened unified Docker image. The production 1.3.4 post-deployment test had failed only because its assertion looked in /web instead of /app/web.
- Trading algorithms, order submission, risk settings, accounts, credentials, live permissions, and V2 feature gates are unchanged. Repeat automated CI, in-image tests and operational health verification against the new immutable image.

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
