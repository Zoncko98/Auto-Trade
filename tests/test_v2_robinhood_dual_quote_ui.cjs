"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const ui=fs.readFileSync(path.join(root,"web/v2-status.js"),"utf8");
const server=fs.readFileSync(path.join(root,"app/dashboard_server.py"),"utf8");
test("the Robinhood preflight labels signed native time separately from public trade checks",()=>{
  assert.match(ui,/Signed quote timestamps:/);
  assert.match(ui,/Independent venue-timed trade crosschecks:/);
  assert.match(ui,/Coinbase trade time remains separately sourced/);
  assert.match(ui,/V2 live cutover:/);
});
test("signed migration evidence stays behind authenticated read-only route",()=>{
  assert.match(server,/if UNIFIED_APP and path == "\/api\/v2\/status":/);
  assert.match(server,/if not nonce:/);
  assert.doesNotMatch(ui,/fetch\("\/api\/v2\/authorize-live/);
  assert.doesNotMatch(ui,/submit_order\(|place_order\(/);
});
