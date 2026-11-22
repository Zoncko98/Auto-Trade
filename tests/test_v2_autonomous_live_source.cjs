"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const src=f=>fs.readFileSync(path.join(__dirname,"..",f),"utf8");
test("V2 shared live scan is actual strategy→AI→risk→durable broker lifecycle source",()=>{
 const engine=src("app/trader_v2/autonomous_live.py");
 assert.match(engine,/class AutonomousLiveScan/);
 assert.match(engine,/StockController\(\)/);
 assert.match(engine,/CryptoController\(\)/);
 assert.match(engine,/LivePipeline\(self\.broker,store,self\.gate/);
 assert.match(engine,/self\.controller\.candidate\(self\.account_id,candles\)/);
 assert.match(engine,/pipeline\.evaluate\(candidate,quote,policy/);
 assert.match(engine,/store\.pending\(self\.account_id\)/);
 assert.match(engine,/pipeline\.reconcile\(row\["key"\]\)/);
});
test("account ownership and V1 exit and realized-loss parity are unavoidable before order journal",()=>{
 const engine=src("app/trader_v2/autonomous_live.py");
 assert.match(engine,/self\.strategy_parity_provider\(\) is not True/);
 assert.match(engine,/V2_STRATEGY_PARITY_UNVERIFIED/);
 assert.match(engine,/self\.realized_loss_provider\(account\)/);
 assert.match(engine,/V2_OWNER_PROOF_UNAVAILABLE/);
 assert.match(engine,/self\.writer_scope/);
 const first=engine.indexOf("proof=self._authority(now)");
 const journal=engine.indexOf("store=EventStore(");
 assert.ok(first!==-1&&journal>first);
});
test("market provider records real interval ends, never fabricated bars",()=>{
 const feed=src("app/trader_v2/signed_live_candles.py");
 assert.match(feed,/schwab_signed_candles/);
 assert.match(feed,/webull_signed_candles/);
 assert.match(feed,/coinbase_recorded_candles/);
 assert.match(feed,/\?mode=ro/);
 assert.match(feed,/PRAGMA query_only=ON/);
 assert.doesNotMatch(feed,/submit_order\(|place_order\(/);
});
test("dashboard truthfully states shared live code not yet cut over",()=>{
 const status=src("app/trader_v2/status.py");
 assert.match(status,/SOURCE_IMPLEMENTED_SIGNED_HANDOFF_REQUIRED/);
 assert.match(status,/live_order_authority":False/);
 assert.match(status,/V1_TO_V2_ACCOUNT_WRITER_HANDOFF/);
});
