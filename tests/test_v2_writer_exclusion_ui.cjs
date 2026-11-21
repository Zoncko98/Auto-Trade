"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=p=>fs.readFileSync(path.join(root,p),"utf8");

test("V1 live broker order paths guard per-account POSTs with the same owner lock",()=>{
  const schwab=read("app/live_worker.py");
  const webull=read("app/webull_worker.py");
  const robinhood=read("app/robinhood_order_pass.py");
  assert.match(schwab,/account_writer_scope\(STATE_DIR\.parent,"schwab",account_hash,owner="V1"\)/);
  assert.match(webull,/account_writer_scope\(root,"webull",account,owner="V1"\)/);
  assert.match(robinhood,/account_writer_scope\(state,"robinhood_crypto",prepared\["account"\],owner="V1"\)/);
  assert.equal((robinhood.match(/owner="V1"/g)||[]).length,2);
  assert.match(schwab,/V1_ORDER_WRITER_OWNERSHIP_TRANSFERRED_OR_UNVERIFIED/);
  assert.match(webull,/V1_ORDER_WRITER_OWNERSHIP_TRANSFERRED_OR_UNVERIFIED/);
  assert.match(robinhood,/V1_ORDER_WRITER_OWNERSHIP_TRANSFERRED_OR_UNVERIFIED/);
});
test("V2 must prove persistent local owner generation in addition to broker handoff",()=>{
  const engine=read("app/trader_v2/live_pipeline.py");
  const guard=read("app/trader_v2/writer_ownership.py");
  assert.match(engine,/ownership_root/);
  assert.match(engine,/generation=proof\.generation/);
  assert.match(engine,/ACCOUNT_WRITER_OWNERSHIP_UNVERIFIED/);
  assert.match(guard,/fcntl\.flock\(fd,fcntl\.LOCK_EX\)/);
  assert.match(guard,/WRITER_OWNER_FILE_INVALID/);
  assert.doesNotMatch(guard,/def stage_owner_for_tests_only|def set_owner/);
});
test("Authenticated signed observations expire and frontend identifies schema failure",()=>{
  const status=read("app/trader_v2/status.py");
  const view=read("web/v2-status.js");
  assert.match(status,/SIGNED_BROKER_PROBE_STALE_OR_UNAVAILABLE/);
  assert.match(view,/Holdings failure:/);
  assert.match(view,/Read-only observation STALE/);
  assert.doesNotMatch(view,/setWriterOwner|submitLiveOrder|forceCutover/);
});
