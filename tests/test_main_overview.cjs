"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
const classes = (...flags) => {
  const values = new Set(flags);
  return {contains:c=>values.has(c),add:c=>values.add(c),
    remove:c=>values.delete(c),toggle:(c,on)=>{on?values.add(c):values.delete(c)}};
};
const nodes = new Map();
for(const id of ["sidebar-account-context","sidebar-current-account",
  "live-nav-group","paper-nav-group","breadcrumb-divider","breadcrumb",
  "live-mode-banner"]) nodes.set(id,{classList:classes("hidden"),textContent:""});
const views = ["workspaces","live","overview","decisions","reviews","brokers","profile"]
  .map(v=>({id:"view-"+v,classList:classes(v==="workspaces"?"":"hidden")}));
const nav = ["workspaces","live","overview","brokers"]
  .map(v=>({dataset:{view:v},classList:classes()}));
const ctx = {loadBrokerWorkspace:async()=>{},document:{getElementById:id=>nodes.get(id),
    querySelectorAll:s=>s===".view"?views:s===".nav-item"?nav:[],
    addEventListener:()=>{}},console,Intl,Date,Number,String,Object,Math};
vm.runInNewContext(source+"\nglobalThis.__showView=showView;",ctx);
const show=ctx.__showView;
const el=id=>nodes.get(id);
const visible=id=>!el(id).classList.contains("hidden");
show("workspaces");
assert.equal(visible("live-nav-group"),false);
assert.equal(visible("paper-nav-group"),false);
assert.equal(visible("sidebar-account-context"),false);
assert.equal(visible("live-mode-banner"),false);
assert.equal(el("breadcrumb").textContent,"All accounts");
assert.equal(views.find(v=>v.id==="view-workspaces").classList.contains("hidden"),false);
show("live");
assert.equal(visible("live-nav-group"),true);
assert.equal(visible("paper-nav-group"),false);
assert.equal(visible("live-mode-banner"),true);
assert.equal(el("sidebar-current-account").textContent,"Schwab live");
assert.equal(views.find(v=>v.id==="view-workspaces").classList.contains("hidden"),true);
show("overview");
assert.equal(visible("paper-nav-group"),true);
assert.equal(visible("live-nav-group"),false);
assert.equal(visible("live-mode-banner"),false);
assert.equal(el("sidebar-current-account").textContent,"Paper Trading");
show("brokers");
assert.equal(visible("live-nav-group"),false);
assert.equal(visible("paper-nav-group"),false);
show("workspaces");
assert.equal(visible("sidebar-account-context"),false);
assert.equal(views.find(v=>v.id==="view-workspaces").classList.contains("hidden"),false);
console.log("PASS: account overview lands first; Schwab, Paper and breadcrumb navigation remain separate");
