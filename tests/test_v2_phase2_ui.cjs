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

test("Schwab V2 stock price bridge reuses V1 quotes without broker submission",()=>{
  const worker=read("app/live_worker.py");
  const html=read("web/index.html");
  assert.match(worker,/normalized_quotes\(quotes,requested=tuple\(UNIVERSE\),now=now\)/);
  assert.match(worker,/write_snapshot\(STATE_DIR,doc\)/);
  assert.match(worker,/except \(MarketDataUnavailable,ImportError,OSError,ValueError,TypeError\)/);
  assert.match(html,/Schwab stock quotes are reused from its existing authenticated V1 scanner/);
});

test("V2 migration preflight shows four isolated brokers without arming orders",()=>{
  const html=read("web/index.html");
  const js=read("web/v2-status.js");
  const status=read("app/trader_v2/status.py");
  const preflight=read("app/trader_v2/cutover_preflight.py");
  assert.match(html,/id="v2-cutover-status"/);
  assert.match(js,/showCutover\(data\.cutover_preflight\)/);
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
