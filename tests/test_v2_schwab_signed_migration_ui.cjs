"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=rel=>fs.readFileSync(path.join(root,rel),"utf8");
test("V2 Schwab signed preflight uses the existing V1 client",()=>{
 const runtime=read("app/live_worker.py");
 const probe=read("app/trader_v2/schwab_migration_probe.py");
 const gate=read("app/trader_v2/launch_gates.py");
 assert.match(runtime,/schwab_migration_probe import run_once/);
 assert.match(probe,/confirm_account/);
 assert.match(probe,/current_broker_orders/);
 assert.match(probe,/market_is_normal/);
 assert.match(probe,/AUTHENTICATED_SCHWAB_READ_ONLY/);
 assert.match(gate,/AUTHENTICATED_SCHWAB_READ_ONLY/);
 assert.doesNotMatch(probe,/client_from_token_file|\.place_order\(|\.cancel_order\(/);
});
test("Trading Operations shows signed Schwab diagnostics without enabling live V2",()=>{
 const ui=read("web/v2-status.js");
 assert.match(ui,/Signed Schwab V2 read-only preflight/);
 assert.match(ui,/signed_observation_fresh===true/);
 assert.match(ui,/V2 live cutover: NOT READY/);
 assert.doesNotMatch(ui,/innerHTML|submit_order\(|place_order\(/);
});
