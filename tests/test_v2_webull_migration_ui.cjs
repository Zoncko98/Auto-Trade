"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const src=(f)=>fs.readFileSync(path.join(root,f),"utf8");
test("Webull V2 signed GET probe is authenticated and CSRF guarded",()=>{
  const server=src("app/dashboard_server.py");
  const auth=server.indexOf("if not nonce:");
  const get=server.indexOf('if UNIFIED_APP and path == "/api/v2/webull-preflight":');
  const post=server.indexOf('if UNIFIED_APP and path == "/api/v2/webull-preflight":',get+10);
  const csrf=server.indexOf("if not self._csrf_ok():",server.indexOf("def do_POST"));
  assert.ok(auth>=0 && get>auth);
  assert.ok(csrf>=0 && post>csrf);
  assert.match(server,/from trader_v2\.webull_probe_runner import run_once/);
});
test("Webull preflight is a visible account-safe diagnostic, not start live",()=>{
  const html=src("web/index.html");
  const ui=src("web/v2-status.js");
  assert.match(html,/id="v2-webull-preflight-run"/);
  assert.match(html,/id="v2-webull-preflight-report"/);
  assert.match(ui,/\/api\/v2\/webull-preflight/);
  assert.match(ui,/X-CSRF-Token/);
  assert.match(ui,/V2 live authority: OFF/);
  assert.doesNotMatch(ui,/place_order\(|submit_order\(|innerHTML/);
});
test("Webull signed GET-only migration probe can never assert live permission",()=>{
  const audit=src("app/trader_v2/webull_migration_probe.py");
  const runner=src("app/trader_v2/webull_probe_runner.py");
  assert.match(audit,/"cutover_ready":False/);
  assert.match(audit,/"live_order_authority":False/);
  assert.match(audit,/broker\.open_orders\(account\)/);
  assert.match(audit,/broker\.order_detail\(account,row\["client_id"\]\)/);
  assert.doesNotMatch(audit,/broker\.place\(|submit_order\(|cancel_order\(/);
  assert.doesNotMatch(runner,/broker\.place\(|submit_order\(|cancel_order\(/);
});
