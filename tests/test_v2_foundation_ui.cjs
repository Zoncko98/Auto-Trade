"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=name=>fs.readFileSync(path.join(root,name),"utf8");
test("V2 foundation is visible under existing operations without a duplicate dashboard",()=>{
 const html=read("web/index.html");
 assert.match(html,/id="view-operations"/);
 assert.match(html,/id="v2-foundation-card"/);
 assert.match(html,/id="v2-foundation-status"/);
 assert.match(html,/id="v2-status-refresh"/);
 assert.match(html,/script defer src="\/v2-status.js"/);
 assert.match(html,/No V2 live-broker order authority/);
});
test("V2 authenticated status is read-only and rejects unauthenticated users",()=>{
 const src=read("app/dashboard_server.py");
 assert.match(src,/if UNIFIED_APP and path == "\/api\/v2\/status"/);
 assert.match(src,/from trader_v2.status import summary/);
 const route=src.indexOf('if UNIFIED_APP and path == "/api/v2/status"');
 const session=src.indexOf('if not nonce:',src.indexOf('if not path.startswith("/api/")'));
 assert.ok(session>=0 && session<route,"auth must precede V2 status");
 const js=read("web/v2-status.js");
 assert.match(js,/credentials:"same-origin"/);
 assert.match(js,/Live broker authority: OFF/);
 // An operator-triggered recorded paper replay is a CSRF-protected POST.
 // Live broker order actions remain forbidden in V2 status/replay UI.
 assert.match(js,/\/api\/v2\/replay\/run/);
 assert.match(js,/X-CSRF-Token/);
 assert.match(js,/simulated_only!==true/);
 assert.doesNotMatch(js,/submit_order|place_order|\/api\/v2\/live/);
});
