"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=file=>fs.readFileSync(path.join(root,file),"utf8");

test("Phase 2 remains inside the existing operations dashboard",()=>{
  const html=read("web/index.html");
  assert.match(html,/id="view-operations"/);
  assert.match(html,/id="v2-adapter-health"/);
  assert.match(html,/id="v2-foundation-card"/);
  assert.doesNotMatch(html,/id="view-v2-live"/);
});
test("Broker readiness presents only verified values and never invented zeros",()=>{
  const ui=read("web/v2-status.js");
  assert.match(ui,/row.read_verified&&row\[key\]!==null/);
  assert.match(ui,/Values unavailable/);
  assert.match(ui,/Buying power/);
  assert.match(ui,/Entry headroom/);
  assert.match(ui,/document\.createElement/);
  assert.match(ui,/\.textContent=/);
  assert.doesNotMatch(ui,/innerHTML|submit_order|place_order/);
});
test("Source-specific adapters cannot create V2 brokerage order writes",()=>{
  const adapters=read("app/trader_v2/readonly_adapters.py");
  const market=read("app/trader_v2/market_sources.py");
  assert.match(adapters,/read-only/gi);
  assert.match(market,/broker_executable:bool=False/);
  assert.match(market,/self\.last,False\)/);
  assert.doesNotMatch(adapters,/\b(place_order|submit_order|cancel_order|TradeClient|WebullBroker\()/);
  assert.doesNotMatch(market,/\b(place_order|submit_order|cancel_order|TradeClient|WebullBroker\()/);
});
test("Authenticated V2 readiness reports broker observations, not live broker permissions",()=>{
  const src=read("app/trader_v2/status.py");
  assert.match(src,/ReadOnlyBrokerRegistry/);
  assert.match(src,/cached_market_status/);
  assert.match(src,/live_order_authority":False/);
  const server=read("app/dashboard_server.py");
  const auth=server.indexOf("if not nonce:");
  const route=server.indexOf('if UNIFIED_APP and path == "/api/v2/status"');
  assert.ok(auth>=0 && auth<route);
});


test("Unified Operations offers read-only V2 why-no-trade diagnostics",()=>{
  const status=read("app/trader_v2/status.py");
  const ui=read("web/v2-status.js");
  const reducer=read("app/trader_v2/readiness.py");
  assert.match(status,/readiness_diagnostics/);
  assert.match(ui,/V2 why no trade/);
  assert.match(ui,/V2_READ_ONLY_NO_ORDER_AUTHORITY/);
  assert.match(ui,/document.createElement\("small"\)/);
  assert.doesNotMatch(ui,/innerHTML|submit_order|place_order/);
  assert.match(reducer,/order_reconciliation/);
  assert.match(reducer,/NOT_VERIFIED/);
});


test("Historical recorded paper replay uses the existing Operations view",()=>{
  const html=read("web/index.html");
  const ui=read("web/v2-status.js");
  assert.match(html,/id="v2-paper-replay-card"/);
  assert.match(html,/id="v2-replay-symbol"/);
  assert.match(html,/id="v2-replay-run"/);
  assert.match(html,/Historical paper replay/);
  assert.match(html,/does not contact a broker/);
  assert.match(ui,/\/api\/v2\/replay\/run/);
  assert.match(ui,/\/api\/session/);
  assert.match(ui,/X-CSRF-Token/);
  assert.match(ui,/credentials:"same-origin"/);
  assert.match(ui,/live_orders_submitted!==0/);
  assert.match(ui,/showRecordedReport/);
  assert.doesNotMatch(ui,/innerHTML|submit_order|place_order/);
});
test("Recorded replay API is authenticated and CSRF gated",()=>{
  const server=read("app/dashboard_server.py");
  const getPos=server.indexOf('if UNIFIED_APP and path == "/api/v2/replay":');
  const authPos=server.indexOf('if not nonce:');
  const postPos=server.indexOf('if UNIFIED_APP and path == "/api/v2/replay/run":');
  const csrfPos=server.indexOf('if not self._csrf_ok():',server.indexOf('def do_POST'));
  assert.ok(authPos>=0 && authPos<getPos);
  assert.ok(csrfPos>=0 && csrfPos<postPos);
  assert.match(server,/run_recorded_replay\(STATE_DIR, payload\["symbol"\]\)/);
  const replay=read("app/trader_v2/recorded_replay.py");
  assert.match(replay,/RECORDED_V1_PAPER_CLOSED_BARS/);
  assert.match(replay,/SimulatedBroker/);
  assert.doesNotMatch(replay,/\b(place_order|submit_order|TradeClient|WebullBroker)\b/);
});


test("AI shadow evidence cannot grant paper or live order permission",()=>{
  const worker=read("app/trader_v2/fresh_paper.py");
  const shadow=read("app/trader_v2/ai_shadow.py");
  const ui=read("web/v2-status.js");
  assert.match(worker,/shadow\(candidate,quote,now=now\)/);
  assert.match(worker,/RiskPolicy\(ai_mode="OFF"\)/);
  assert.match(shadow,/SharedAIReviewer/);
  assert.match(shadow,/OllamaReviewTransport/);
  assert.match(shadow,/changed_order_authority/);
  assert.match(ui,/AI shadow:/);
  assert.match(ui,/AI has no order authority/);
  assert.doesNotMatch(shadow,/submit_order|place_order|RobinhoodCryptoAdapter|WebullBroker/);
});

test("Paper scan scorecard is read-only evidence, not live performance",()=>{
  const worker=read("app/trader_v2/fresh_paper.py");
  const ledger=read("app/trader_v2/scan_observability.py");
  const status=read("web/v2-status.js");
  assert.match(worker,/capture_scan\(root,report\)/);
  assert.match(worker,/read_scorecards\(base\)/);
  assert.match(ledger,/paper_scan_history.sqlite3/);
  assert.match(ledger,/mode=ro/);
  assert.match(ledger,/live_orders_submitted/);
  assert.doesNotMatch(ledger,/submit_order|place_order|SchwabClient|RobinhoodCryptoAdapter/);
  assert.match(status,/24h paper scan history/);
  assert.match(status,/marked P\/L/);
  assert.match(status,/Peak-to-trough paper drawdown/);
});

test("Schwab V2 stock shadow uses genuine source candles and stays read-only",()=>{
  const worker=read("app/trader_v2/stock_shadow.py");
  const runtime=read("app/unified_runtime.py");
  const stock=read("app/live_worker.py");
  const html=read("web/index.html");
  const js=read("web/v2-status.js");
  const server=read("app/dashboard_server.py");
  assert.match(worker,/class StockShadowError/);
  assert.match(worker,/from autonomous_selector import UNIVERSE/);
  assert.match(worker,/StockController\(\)/);
  assert.match(worker,/granularity_seconds": 300/);
  assert.match(worker,/signals_recorded/);
  assert.match(worker,/"live_orders_submitted": 0/);
  assert.match(worker,/"broker_sdk_calls": 0/);
  assert.doesNotMatch(worker,/submit_order|place_order|from schwab\.auth|client_from_token_file/);
  assert.match(runtime,/spawn\("v2-stock-shadow"/);
  assert.match(runtime,/if enabled\["live"\]/);
  assert.match(stock,/return bars/);
  assert.match(stock,/capture_schwab_candles\(STATE_DIR, symbol, bars, now=now\)/);
  assert.match(html,/id="v2-stock-shadow-card"/);
  assert.match(html,/id="v2-stock-shadow-status"/);
  assert.match(html,/id="v2-stock-shadow-symbols"/);
  assert.match(js,/readStockShadowStatus\(\)/);
  assert.match(js,/\/api\/v2\/stock-shadow/);
  assert.match(server,/path == "\/api\/v2\/stock-shadow"/);
});

test("Schwab V2 stock price bridge reuses V1 quotes without broker submission",()=>{
  const worker=read("app/live_worker.py");
  const html=read("web/index.html");
  assert.match(worker,/normalized_quotes\(quotes,requested=tuple\(UNIVERSE\),now=now\)/);
  assert.match(worker,/write_snapshot\(STATE_DIR,doc\)/);
  assert.match(worker,/except \(MarketDataUnavailable,ImportError,OSError,ValueError,TypeError\)/);
  assert.match(html,/Schwab stock quotes are reused from its existing authenticated V1 scanner/);
});

test("V2 actual simulated P/L is reconciled after fees with no live claims",()=>{
  const econ=read("app/trader_v2/sim_economics.py");
  const fresh=read("app/trader_v2/fresh_paper.py");
  const ui=read("web/v2-status.js");
  const html=read("web/index.html");
  assert.match(econ,/SIMULATED_CASH_AND_POSITIONS_RECONCILED/);
  assert.match(econ,/SIMULATOR_RECONCILIATION_REQUIRED/);
  assert.match(econ,/STARTING_CASH=Decimal/);
  assert.match(econ,/"live_orders_authorized":False/);
  assert.match(fresh,/"economic_reconciliation":read_economics\(base,now=now\)/);
  assert.match(html,/id="v2-paper-econ-report"/);
  assert.match(ui,/showPaperEconomics\(data\)/);
  assert.match(ui,/Realized net after fees/);
  assert.match(ui,/No performance claim/);
  assert.doesNotMatch(econ,/place_order\(|submit_order\(|from schwab\.|from robinhood/);
});

test("V2 rolling paper scan journal persists fee-shadow decisions without broker authority",()=>{
  const store=read("app/trader_v2/scan_observability.py");
  const report=read("app/trader_v2/paper_activity.py");
  const ui=read("web/v2-status.js");
  assert.match(store,/ALTER TABLE paper_scans ADD COLUMN fee_shadow_state TEXT/);
  assert.match(store,/fee_shadow_state=CASE/);
  assert.match(store,/excluded.fee_shadow_state != 'NOT_INVOKED'/);
  assert.match(report,/fee_shadow_coverage/);
  assert.match(report,/fee_shadow_observations/);
  assert.match(ui,/insufficient net upside/);
  assert.match(ui,/Fee\/reward shadow/);
  assert.doesNotMatch(report,/place_order\(|submit_order\(/);
});

test("V2 fee-aware crypto shadow cannot veto a simulated or live order",()=>{
  const policy=read("app/trader_v2/crypto_fee_shadow.py");
  const worker=read("app/trader_v2/fresh_paper.py");
  const html=read("web/index.html");
  const ui=read("web/v2-status.js");
  assert.match(policy,/ADVISORY_COUNTERFACTUAL_ONLY/);
  assert.match(policy,/SHADOW_REJECT_REWARD_AFTER_FEES/);
  assert.match(policy,/EXIT_NOT_GATED/);
  assert.match(policy,/"changed_execution": False/);
  assert.match(policy,/"live_order_authorized": False/);
  assert.match(worker,/fee_evidence=fee_shadow_assess\(candidate,quote,bars,now=now\)/);
  assert.match(worker,/fee_shadow":fee_evidence/);
  assert.match(worker,/PaperPipeline\(broker,journal\)\.evaluate/);
  assert.match(ui,/Fee\/reward shadow/);
  assert.match(html,/cannot veto actual paper orders/);
  assert.doesNotMatch(policy,/place_order\(|submit_order\(|from robinhood\.|from schwab\./);
});

test("V2 paper rolling 3h/24h activity separates signals, blockers and simulated fills",()=>{
  const source=read("app/trader_v2/paper_activity.py");
  const fresh=read("app/trader_v2/fresh_paper.py");
  const ui=read("web/v2-status.js");
  const html=read("web/index.html");
  assert.match(source,/SIMULATED_LEDGER_VERIFIED/);
  assert.match(source,/FILL_LEDGER_UNVERIFIED/);
  assert.match(source,/ENTRY_BLOCKED/);
  assert.match(source,/EXIT_BLOCKED/);
  assert.match(source,/"live_orders_authorized": False/);
  assert.match(fresh,/"activity_3h":read_activity\(base,hours=3,now=now\)/);
  assert.match(fresh,/"activity_24h":read_activity\(base,hours=24,now=now\)/);
  assert.match(html,/id="v2-paper-activity-report"/);
  assert.match(ui,/showPaperActivity\(data\)/);
  assert.match(ui,/Why no trade:/);
  assert.match(ui,/Simulated fills unavailable/);
  assert.doesNotMatch(source,/place_order\(|submit_order\(|from schwab\.|from robinhood/);
});

test("Fast V2 Ollama shadow shows bounded latency and no broker execution path",()=>{
  const transport=read("app/trader_v2/ollama_transport.py");
  const shared=read("app/trader_v2/ai_service.py");
  const stock=read("app/trader_v2/stock_shadow.py");
  const ui=read("web/v2-status.js");
  assert.match(transport,/"think": False/);
  assert.match(transport,/"num_predict": 90/);
  assert.match(transport,/"additionalProperties": False/);
  assert.match(transport,/\/api\/chat/);
  assert.match(shared,/MODEL_TIMEOUT/);
  assert.match(stock,/"changed_order_authority": False/);
  assert.match(ui,/review\.latency_ms/);
  assert.doesNotMatch(transport,/submit_order\(|place_order\(|TradeClient\(/);
});

test("V1 source-faithful risk headroom preview never grants a V2 order",()=>{
  const preview=read("app/trader_v2/risk_envelopes.py");
  const cutover=read("app/trader_v2/cutover_preflight.py");
  const ui=read("web/v2-status.js");
  const html=read("web/index.html");
  assert.match(preview,/V1_SCHWAB_VERIFIED_CASH_EQUITY_EXPOSURE/);
  assert.match(preview,/V1_WEBULL_CASH_25PCT_AND_EXPOSURE_25PCT_LIMIT/);
  assert.match(preview,/ROBINHOOD_BUYING_POWER_ONLY_NOT_CASH_EQUITY/);
  assert.match(preview,/"v2_order_authorized":False/);
  assert.match(preview,/"ready_to_submit":False/);
  assert.doesNotMatch(preview,/submit_order\(|place_order\(|get_account\(/);
  assert.match(cutover,/risk_envelope":budget/);
  assert.match(ui,/Effective V1 risk budget preview:/);
  assert.match(ui,/Does NOT authorize any V2 order/);
  assert.match(html,/NOT V2 broker-order approval/);
});

test("V2 migration preflight shows four isolated brokers without arming orders",()=>{
  const html=read("web/index.html");
  const js=read("web/v2-status.js");
  const status=read("app/trader_v2/status.py");
  const preflight=read("app/trader_v2/cutover_preflight.py");
  assert.match(html,/id="v2-cutover-status"/);
  assert.match(js,/showCutover\(data\.cutover_preflight,data\.robinhood_signed_migration_probe,\s*data\.v2_live_launch\)/);
  assert.match(js,/V2 live cutover: NOT READY/);
  assert.match(js,/automatic_cutover_allowed!==false/);
  assert.match(status,/status\["cutover_preflight"\]=preflight\(/);
  assert.match(preflight,/READ_ONLY_V2_LIVE_CUTOVER_PREFLIGHT/);
  assert.match(preflight,/"automatic_cutover_allowed":False/);
  assert.match(preflight,/V1_ORDER_WRITER_MUST_BE_PAUSED_FOR_CUTOVER/);
  assert.doesNotMatch(preflight,/submit_order\(|place_order\(|TradeClient\(/);
});

test("Fresh market V2 paper worker has no live broker controls",()=>{
  const html=read("web/index.html");
  const js=read("web/v2-status.js");
  const server=read("app/dashboard_server.py");
  const runtime=read("app/unified_runtime.py");
  const worker=read("app/trader_v2/fresh_paper.py");
  const source=read("app/trader_v2/public_crypto.py");
  assert.match(html,/id="v2-paper-fresh-card"/);
  assert.match(html,/id="v2-paper-fresh-report"/);
  assert.match(js,/\/api\/v2\/paper-fresh/);
  assert.match(js,/WARMING_UP|scan_state/);
  assert.doesNotMatch(js,/innerHTML|submit_order|place_order/);
  assert.match(server,/path == "\/api\/v2\/paper-fresh"/);
  assert.match(runtime,/enabled\["v2_paper"\]=bool\(cfg\["paper_enabled"\]\)/);
  assert.match(worker,/SimulatedBroker/);
  assert.match(worker,/Coinbase|COINBASE_PUBLIC_TICKER_ONLY/i);
  assert.doesNotMatch(worker,/\b(TradeClient|WebullBroker|RobinhoodCryptoAdapter)\b/);
  assert.match(source,/https:\/\/api\.exchange\.coinbase\.com\/products\//);
});
