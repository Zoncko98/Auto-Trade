"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
function read(p){return fs.readFileSync(path.join(root,p),"utf8");}
test("Schwab dashboard distinguishes paused account monitoring from offline worker",()=>{
 const audit=read("web/ui-audit.js"), app=read("web/app.js");
 assert.match(audit,/Order scan paused · account monitoring online/);
 assert.match(app,/Live orders paused · read-only account monitor online/);
 assert.match(audit,/Broker snapshot stale\/unverified/);
});
test("Schwab held-market candle gaps block orders without halting heartbeat loop",()=>{
 const src=read("app/live_worker.py");
 assert.match(src,/HELD_CANDLES_UNAVAILABLE/);
 assert.match(src,/if unavailable_held:[\s\S]*?return/);
 assert.match(src,/refresh_paused_account\(/);
 assert.match(src,/write_heartbeat\(activated and broker_snapshot_verified,next_mode\)/);
 const supervisor=read("app/unified_runtime.py");
 assert.match(supervisor,/Live worker stopped; operator review required/);
 assert.match(supervisor,/if not live_stop_logged/);
});
