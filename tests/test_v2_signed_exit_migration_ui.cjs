"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=rel=>fs.readFileSync(path.join(root,rel),"utf8");
test("V2 account exit source comparison never claims full parity",()=>{
 const view=read("web/v2-status.js");
 const exec=read("app/trader_v2/autonomous_live.py");
 const gate=read("app/trader_v2/launch_gates.py");
 assert.match(view,/FULL V1 PARITY NOT VERIFIED/);
 assert.match(exec,/V2_EXIT_EVIDENCE_UNVERIFIED/);
 assert.match(exec,/exit_evidence_provider/);
 assert.match(gate,/_check\("V1_AI_AND_EXIT_PARITY",False/);
});
test("Webull signed quote is observation, not order acceptance",()=>{
 const view=read("web/v2-status.js");
 const probe=read("app/trader_v2/webull_migration_probe.py");
 assert.match(view,/SIGNED READ-ONLY OBSERVATION/);
 assert.match(probe,/broker_quote_timestamp_verified_symbols/);
 assert.match(view,/V2 live authority: OFF/);
});
