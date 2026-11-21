"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const source=fs.readFileSync(path.join(root,"app/trader_v2/robinhood_live_adapter.py"),"utf8");
test("all holdings use signed broker quotes and strict timestamps, without Coinbase LAST valuation",()=>{
  const start=source.indexOf("def _signed_holding_ask(");
  const end=source.indexOf("def account(",start);
  assert.ok(start>0&&end>start);
  const valuation=source.slice(start,end);
  assert.match(valuation,/robinhood_market_quote\(payload,symbol,now=end\)/);
  assert.match(valuation,/quote\.observed_at/);
  assert.match(valuation,/SIGNED_HOLDING_MARK_STALE_OR_UNTRADABLE/);
  assert.doesNotMatch(valuation,/public_trade_feed|submit_order|place_order/);
  assert.match(source,/market_exposure\+=qty\*ask/);
  assert.match(source,/raise BrokerEvidenceUnavailable\("SIGNED_POSITION_MARK_UNVERIFIED"\)/);
});
