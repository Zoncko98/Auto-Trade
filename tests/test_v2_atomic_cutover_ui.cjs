"use strict";
const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=p=>fs.readFileSync(path.join(root,p),"utf8");
test("approved Robinhood cutover is account-scoped and parent-only",()=>{
 const runtime=read("app/unified_runtime.py");
 const handoff=read("app/trader_v2/cutover_robinhood.py");
 assert.match(runtime,/AUTO_TRADER_V2_ROBINHOOD_CUTOVER/);
 assert.match(runtime,/AUTO_TRADER_V2_ROBINHOOD_ACCOUNT_DIGEST/);
 assert.match(runtime,/stop_v1=lambda:stop_process\("robinhood"\)/);
 assert.match(handoff,/account_writer_scope\(/);
 assert.match(handoff,/transfer_writer\(/);
 assert.match(handoff,/CUTOVER_APPROVED_ACCOUNT_NOT_SELECTED/);
 assert.match(handoff,/LEGACY_MANAGED_LOTS_REQUIRE_ADOPTION/);
});
test("existing broker UI shows verified owner count and actual engine outcome",()=>{
 const ui=read("web/v2-status.js");
 const supervisor=read("app/trader_v2/live_supervisor.py");
 assert.match(ui,/Migrated brokers: /);
 assert.match(ui,/OWNER TRANSFERRED/);
 assert.match(ui,/Latest signed V2 scan result:/);
 assert.match(supervisor,/confirmed_owners/);
 assert.match(supervisor,/v2_account_owner/);
 assert.doesNotMatch(ui,/innerHTML/);
});
