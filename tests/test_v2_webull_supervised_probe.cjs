"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const runtime=fs.readFileSync(path.join(root,"app/unified_runtime.py"),"utf8");
const runner=fs.readFileSync(path.join(root,"app/trader_v2/webull_probe_runner.py"),"utf8");
test("same existing supervisor runs signed Webull read-only migration audit",()=>{
 assert.match(runtime,/v2_webull_probe_last_spawn=0\.0/);
 assert.match(runtime,/spawn\("v2-webull-probe"/);
 assert.match(runtime,/trader_v2\.webull_probe_runner/);
 assert.match(runtime,/time\.monotonic\(\)-v2_webull_probe_last_spawn>=900/);
 assert.match(runtime,/stop_process\("v2-webull-probe"\)/);
});
test("Webull background audit never becomes an order writer",()=>{
 assert.match(runner,/def run_once\(state, signed_broker=None/);
 assert.match(runner,/def main\(\)/);
 assert.match(runner,/broker_open_orders_verified/);
 assert.match(runner,/"live_order_authority":False/);
 assert.doesNotMatch(runner,/submit_order\(|place_order\(|cancel_order\(/);
});
