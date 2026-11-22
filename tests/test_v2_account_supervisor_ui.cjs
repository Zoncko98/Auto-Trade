"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=rel=>fs.readFileSync(path.join(root,rel),"utf8");
test("V2 standby coordinator has no broker writer dependency",()=>{
 const source=read("app/trader_v2/live_supervisor.py");
 const supervisor=read("app/unified_runtime.py");
 assert.match(source,/READ_ONLY_STANDBY/);
 assert.match(source,/v2_live_order_authority/);
 assert.match(supervisor,/spawn\("v2-live-supervisor"/);
 assert.match(supervisor,/minimal_env/);
 assert.doesNotMatch(source,/submit_order\(|place_order\(|cancel_order\(/);
});
test("authenticated operations shows verified standby vs live writer",()=>{
 const ui=read("web/v2-status.js");
 const status=read("app/trader_v2/status.py");
 assert.match(ui,/SUPERVISED READ-ONLY STANDBY/);
 assert.match(ui,/V2 live writer: NOT ACTIVE/);
 assert.match(ui,/V1 day limits inherited/);
 assert.match(ui,/SIGNED CHECKED/);
 assert.match(status,/live_supervisor_status\(state_dir\)/);
 assert.doesNotMatch(ui,/innerHTML|submit_order\(|place_order\(/);
});
