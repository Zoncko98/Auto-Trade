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
