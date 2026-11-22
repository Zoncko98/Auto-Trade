"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
function source(file){return fs.readFileSync(path.join(root,file),"utf8");}
test("authenticated V2 status includes broker launch acceptance evidence",()=>{
 const status=source("app/trader_v2/status.py");
 assert.match(status,/status\["v2_live_launch"\]=all_launch_status\(state_dir\)/);
 assert.match(status,/live_order_authority":False/);
 const http=source("app/dashboard_server.py");
 assert.match(http,/if not nonce:/);
});
test("existing UI provides collapsed per-broker launch blockers, not an unsafe launch button",()=>{
 const js=source("web/v2-status.js");
 assert.match(js,/launchChecks=new Map/);
 assert.match(js,/document\.createElement\("details"\)/);
 assert.match(js,/V2 launch acceptance:/);
 assert.match(js,/Outstanding acceptance gates:/);
 assert.match(js,/data\.v2_live_launch/);
 assert.doesNotMatch(js,/POST.*\/api\/v2\/live-launch/);
});
test("no operational V2 live authority follows signed quote or buying power",()=>{
 const state=source("app/trader_v2/launch_gates.py");
 assert.match(state,/SIGNED_SETTLEMENT_NOT_CERTIFIED/);
 assert.match(state,/V2_AI_EXIT_AND_COOLDOWN_POLICY_INCOMPLETE/);
 assert.match(state,/V1_TO_V2_HANDOFF_NOT_PERFORMED/);
 assert.match(state,/LIVE_V2_WORKER_NOT_REGISTERED/);
 assert.match(state,/live_v2_order_authority":False/);
 assert.doesNotMatch(state,/submit_order\(|transfer_writer\(|place_order\(/);
});
