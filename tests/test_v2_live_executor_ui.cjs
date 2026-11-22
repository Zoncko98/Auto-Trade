"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const read=f=>fs.readFileSync(path.resolve(__dirname,"..",f),"utf8");
test("TrueNAS parent registers singleton V2 executor in existing app",()=>{
 const runtime=read("app/unified_runtime.py");
 assert.match(runtime,/spawn\("v2-live-executor"/);
 assert.match(runtime,/v2_executor_last_spawn/);
 assert.match(runtime,/"v2-live-executor","v2-live-supervisor"/);
});
test("Dashboard differentiates registered process from V2 order authority",()=>{
 const js=read("web/v2-status.js");
 assert.match(js,/Replacement execution process:/);
 assert.match(js,/V2 live writer: NOT ACTIVE/);
 assert.match(js,/V2 execution admission:/);
 assert.match(read("app/trader_v2/live_supervisor.py"),/executor_status/);
});
