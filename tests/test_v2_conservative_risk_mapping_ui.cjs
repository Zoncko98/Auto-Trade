"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const ui=fs.readFileSync(path.join(root,"web/v2-status.js"),"utf8");
const preflight=fs.readFileSync(path.join(root,"app/trader_v2/cutover_preflight.py"),"utf8");
const mapping=fs.readFileSync(path.join(root,"app/trader_v2/conservative_risk_map.py"),"utf8");
test("V2 cutover panel labels risk mapping observational, not live",()=>{
 assert.match(ui,/V2 numeric risk mapping:/);
 assert.match(ui,/not live permission/);
 assert.match(preflight,/v2_risk_mapping/);
 assert.match(preflight,/v2_live_order_authorized":False/);
});
test("risk mapping retains broker protections and cannot start an order",()=>{
 assert.match(mapping,/V1_AI_AND_EXIT_POLICY_PARITY/);
 assert.match(mapping,/SETTLED_FUNDING/);
 assert.match(mapping,/EXCLUSIVE_V1_V2_HANDOFF/);
 assert.match(mapping,/SIGNED_EXECUTABLE_QUOTE/);
 assert.match(mapping,/max_daily_loss=daily/);
 assert.doesNotMatch(mapping,/\.submit\(|\.place\(|submit_order\(|place_order\(/);
});
