"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=file=>fs.readFileSync(path.join(root,file),"utf8");
test("Signed Robinhood migration probe is supervised read only",()=>{
  const worker=read("app/trader_v2/migration_probe.py");
  const runtime=read("app/unified_runtime.py");
  assert.match(runtime,/spawn\("v2-robinhood-probe"/);
  assert.match(worker,/RobinhoodCryptoAdapter\.from_state/);
  assert.match(worker,/AUTHENTICATED_SIGNED_READ_ONLY/);
  assert.match(worker,/cutover_ready":False/);
  assert.match(worker,/v2_live_order_authority":False/);
  assert.doesNotMatch(worker,/\.(submit_order|cancel_order|place_order)\(/);
});
test("Source-faithful production status is displayed in existing operations panel",()=>{
  const server=read("app/dashboard_server.py");
  const status=read("app/trader_v2/status.py");
  const ui=read("web/v2-status.js");
  assert.match(status,/robinhood_signed_migration_probe/);
  assert.match(ui,/Signed V2 broker audit:/);
  assert.match(ui,/Signed quote timestamps:/);
  assert.match(ui,/showCutover\(data\.cutover_preflight,data\.robinhood_signed_migration_probe,\s*data\.v2_live_launch,\s*data\.v2_live_reconciliation,\s*data\.v2_live_supervisor\)/);
  assert.ok(server.indexOf('if not nonce:')<
             server.indexOf('if UNIFIED_APP and path == "/api/v2/status"'));
  assert.doesNotMatch(ui,/submit_order\(|place_order\(/);
});
test("Migrated order writer is not automatically launched by V1 runtime",()=>{
  const runtime=read("app/unified_runtime.py");
  const engine=read("app/trader_v2/live_pipeline.py");
  assert.match(engine,/V1_TO_V2_SINGLE_WRITER_HANDOFF_UNVERIFIED/);
  assert.match(engine,/isinstance\(broker,SimulatedBroker\)/);
  assert.doesNotMatch(runtime,/spawn\("v2-robinhood-live"/);
  assert.doesNotMatch(runtime,/AUTO_TRADER_V2_FORCE_LIVE/);
});
