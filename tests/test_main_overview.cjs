"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
const html = fs.readFileSync(path.join(__dirname,"../web/index.html"),"utf8");
const sidebar = html.split('<aside class="sidebar">')[1].split("</aside>")[0];
const workspace = html.split('<section class="view" id="view-workspaces">')[1].split('<div class="workspace-section-bar"><h2>Available accounts</h2>')[0];
// Both cross-account entries belong to account overview, not the broker sidebar.
for(const view of ["local","operations"]){
  assert.equal((html.match(new RegExp('data-view="'+view+'"',"g"))||[]).length,1);
  assert.match(workspace,new RegExp('data-view="'+view+'"'));
  assert.doesNotMatch(sidebar,new RegExp('data-view="'+view+'"'));
}
assert.doesNotMatch(sidebar,/robinhood-models/);
assert.doesNotMatch(html,/id="view-robinhood-models"/);
assert.doesNotMatch(html,/id="robinhood-ai-models"/);
assert.match(workspace,/Shared tools/);
assert.match(html,/id="view-local"/);
assert.match(html,/id="view-operations"/);
const classes = (...flags) => {
  const values = new Set(flags);
  return {contains:c=>values.has(c),add:c=>values.add(c),
    remove:c=>values.delete(c),toggle:(c,on)=>{on?values.add(c):values.delete(c)}};
};
const nodes = new Map();
for(const id of ["sidebar-account-context","sidebar-current-account",
  "live-nav-group","paper-nav-group","robinhood-nav-group","breadcrumb-divider","breadcrumb",
  "live-mode-banner"]) nodes.set(id,{classList:classes("hidden"),textContent:""});
const views = ["workspaces","live","overview","decisions","reviews","brokers","profile","local","operations","robinhood"]
  .map(v=>({id:"view-"+v,classList:classes(v==="workspaces"?"":"hidden")}));
const nav = ["workspaces","live","overview","brokers"]
  .map(v=>({dataset:{view:v},classList:classes()}));
const ctx = {loadBrokerWorkspace:async()=>{},loadLocalModels:async()=>{},document:{getElementById:id=>nodes.get(id),
    querySelectorAll:s=>s===".view"?views:s===".nav-item"?nav:[],
    addEventListener:()=>{}},console,Intl,Date,Number,String,Object,Math};
vm.runInNewContext(source+"\nglobalThis.__showView=showView;loadOperations=async()=>{};loadRobinhoodWorkspace=async()=>{};refreshRobinhoodTile=async()=>{};",ctx);
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
show("robinhood");
assert.equal(visible("robinhood-nav-group"),true);
assert.equal(visible("live-nav-group"),false);
assert.equal(el("sidebar-current-account").textContent,"Robinhood Crypto");
show("local");
assert.equal(visible("live-nav-group"),false);
assert.equal(visible("robinhood-nav-group"),false);
assert.equal(visible("sidebar-account-context"),false);
assert.equal(visible("live-mode-banner"),false);
assert.equal(el("breadcrumb").textContent,"AI workstation models");
assert.equal(views.find(v=>v.id==="view-local").classList.contains("hidden"),false);
show("operations");
assert.equal(visible("live-nav-group"),false);
assert.equal(visible("robinhood-nav-group"),false);
assert.equal(visible("paper-nav-group"),false);
assert.equal(visible("sidebar-account-context"),false);
assert.equal(el("breadcrumb").textContent,"Trading operations");
assert.equal(views.find(v=>v.id==="view-operations").classList.contains("hidden"),false);
show("workspaces");
assert.equal(visible("sidebar-account-context"),false);
assert.equal(views.find(v=>v.id==="view-workspaces").classList.contains("hidden"),false);
console.log("PASS: shared tools appear only on account overview; Schwab, Robinhood and Paper navigation stays contextual");
