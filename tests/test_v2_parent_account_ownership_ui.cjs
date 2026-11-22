"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const text=name=>fs.readFileSync(path.join(root,name),"utf8");
test("Legacy broker worker restarts are account-scoped by durable ownership",()=>{
 const source=text("app/unified_runtime.py");
 assert.match(source,/v1_worker_placement\(STATE,"robinhood_crypto"\)/);
 assert.match(source,/v1_worker_placement\(STATE,"webull"\)/);
 assert.match(source,/v1_worker_placement\(STATE,"schwab",config=cfg\)/);
 assert.match(source,/if not rh_ready or not rh_v1\.may_run/);
 assert.match(source,/if not wb_ready or not wb_v1\.may_run/);
 assert.match(source,/schwab_v1\.may_run/);
});
test("Owner mismatch cannot silently enable replacement live order writer",()=>{
 const policy=text("app/trader_v2/worker_placement.py");
 assert.match(policy,/V2_ACCOUNT_OWNER_NO_V1_RESTART/);
 assert.match(policy,/V1_WRITER_OWNERSHIP_UNVERIFIED/);
 assert.doesNotMatch(policy,/submit_order\(|place_order\(|post_order\(/);
 const supervisor=text("app/trader_v2/live_supervisor.py");
 const view=text("web/v2-status.js");
 assert.match(supervisor,/v1_worker_owner_state/);
 assert.match(view,/V1 account writer lifecycle/);
});
