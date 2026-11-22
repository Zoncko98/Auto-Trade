"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const source=name=>fs.readFileSync(path.join(__dirname,"..",name),"utf8");
test("existing unified runtime supervises bounded GET-only Robinhood recovery",()=>{
 const runtime=source("app/unified_runtime.py");
 assert.match(runtime,/v2_robinhood_reconcile_last_spawn=0\.0/);
 assert.match(runtime,/spawn\("v2-robinhood-recovery"/);
 assert.match(runtime,/trader_v2\.live_readonly_reconciler/);
 assert.match(runtime,/time\.monotonic\(\)-v2_robinhood_reconcile_last_spawn>=120/);
 assert.match(runtime,/stop_process\("v2-robinhood-recovery"\)/);
});
test("signed receipt worker never creates or submits broker order",()=>{
 const worker=source("app/trader_v2/live_readonly_reconciler.py");
 assert.match(worker,/RobinhoodReadOnlyReceiptAdapter/);
 assert.match(worker,/INTENTS_NOT_SENT_NO_AUTOMATIC_RETRY/);
 assert.match(worker,/ACCOUNT_OR_ORIGINAL_INTENT_UNVERIFIED/);
 assert.match(worker,/SIGNED_BROKER_ACCOUNT_REQUIRED/);
 assert.match(worker,/orders_submitted":0/);
 assert.doesNotMatch(worker,/\.submit\(|submit_order\(|\.cancel\(|\.place_order\(/);
});
test("authenticated existing Trading Operations panel reports signed V2 order recovery",()=>{
 const status=source("app/trader_v2/status.py");
 const ui=source("web/v2-status.js");
 assert.match(status,/v2_live_reconciliation/);
 assert.match(ui,/V2 signed order recovery:/);
 assert.match(ui,/GET-only, no new orders/);
 assert.match(ui,/data\.v2_live_reconciliation/);
 assert.doesNotMatch(ui,/\/api\/v2\/recovery-activate/);
});
