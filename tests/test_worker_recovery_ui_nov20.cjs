"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=p=>fs.readFileSync(path.join(root,p),"utf8");
test("Schwab dashboard reports safe worker recovery and separate scan blockers",()=>{
 const audit=read("web/ui-audit.js");
 const local=read("web/local.js");
 const backend=read("app/live_dashboard.py");
 assert.match(audit,/worker_supervisor\?\.state==="RECONCILIATION_REQUIRED"/);
 assert.match(audit,/worker_supervisor\?\.state==="RECOVERING"/);
 assert.match(audit,/last_scan_health\?\.state==="PRE_ORDER_BLOCKED"/);
 assert.match(local,/lastLive=data/);
 assert.match(local,/workerState==="RECONCILIATION_REQUIRED"/);
 assert.match(backend,/"worker_supervisor"/);
 assert.match(backend,/"last_scan_health"/);
});
test("Supervisor never restarts with uncertain orders and has a retry budget",()=>{
 const src=read("app/unified_runtime.py");
 assert.match(src,/live_journal_safe_for_restart\(STATE\)/);
 assert.match(src,/len\(live_recovery_attempts\)>=3/);
 assert.match(src,/now-live_last_spawn_at>=120/);
 assert.match(src,/BROKER_ORDER_RECONCILIATION_REQUIRED/);
 assert.match(src,/live_supervisor_event\("RECONCILIATION_REQUIRED"/);
});
test("Worker publishes fail-closed preflight status after an eligible safe block",()=>{
 const src=read("app/live_worker.py");
 assert.match(src,/if not no_ambiguous_order_intent\(ledger\):\s+raise/);
 assert.match(src,/write_heartbeat\(False,operator_mode\(\)\)/);
 assert.match(src,/"state":"PRE_ORDER_BLOCKED"/);
 assert.match(src,/and not cycle_blocked,next_mode/);
});

test("Webull and Robinhood display true reasons for no orders",()=>{
 const app=read("web/app.js");
 const audit=read("web/ui-audit.js");
 assert.match(app,/ARMED_WAITING_QUALIFIED_SIGNAL/);
 assert.match(app,/stock account also has \$0 permitted cash\/exposure headroom/);
 assert.match(app,/Broker policy is armed; no entry passed every signal, fee and AI gate/);
 assert.match(audit,/Policy armed · no qualified signal or approved entry this scan/);
});