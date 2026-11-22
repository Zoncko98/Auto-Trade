"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=p=>fs.readFileSync(path.join(root,p),"utf8");
test("Robinhood risk controls show persisted stale bot order TTL",()=>{
 const page=read("web/index.html"),app=read("web/app.js");
 assert.match(page,/id="robinhood-risk-stale-entry"/);
 assert.match(page,/Use 0 to disable/);
 assert.match(app,/stale_entry_cancel_minutes/);
 assert.match(app,/Stale bot entry:/);
});
test("Only original zero-filled Robinhood order can be canceled once",()=>{
 const processor=read("app/robinhood_stale_entry.py");
 const worker=read("app/robinhood_worker.py");
 const journal=read("app/robinhood_order_journal.py");
 assert.match(processor,/STALE_BUY_ZERO_FILL_NOT_CONFIRMED/);
 assert.match(processor,/account_writer_scope/);
 assert.match(processor,/STALE_BUY_CANCEL_ALREADY_REQUESTED/);
 assert.match(journal,/mark_cancel_requested/);
 assert.match(worker,/reconcile_stale_entry/);
});
