"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const root=path.join(__dirname,"..");
const html=fs.readFileSync(path.join(root,"web/index.html"),"utf8");
const css=fs.readFileSync(path.join(root,"web/workspace.css"),"utf8");
const app=fs.readFileSync(path.join(root,"web/app.js"),"utf8");
const local=fs.readFileSync(path.join(root,"web/local.js"),"utf8");
const audit=fs.readFileSync(path.join(root,"web/ui-audit.js"),"utf8");
const backend=fs.readFileSync(path.join(root,"app/dashboard_server.py"),"utf8");
const ids=Array.from(html.matchAll(/\bid="([^"]+)"/g),x=>x[1]);
assert.equal(new Set(ids).size,ids.length,"Duplicate DOM id detected");
assert(html.includes('src="/ui-audit.js"'));
assert(backend.includes('"/ui-audit.js": ("ui-audit.js"'));
for(const [view,header] of [
 ["live","Schwab trading account"],["robinhood","Robinhood Crypto account"],
 ["webull","Webull stock/crypto account"],["overview","Paper simulator"]]){
  assert(html.includes('<h1>'+header+'</h1>'));
  assert(html.includes('id="view-'+view+'"'));
}
for(const view of ["live-orders","robinhood-orders","webull-orders","trades"]){
 assert(html.includes('data-view="'+view+'"'),"Missing navigable order route: "+view);
}
for(const key of ["webull-risk","robinhood-risk"]){
 const start=html.indexOf('id="'+key+'-form"');
 assert(start>=0);
 assert(html.substring(start,start+600).includes('settings-layout'),key);
}
assert(html.includes('id="webull-risk-current-policy"'));
assert(html.includes('id="audit-live-order-rows"'));
assert(html.includes('id="audit-robinhood-orders"'));
assert(css.includes('.workspace-tile-grid{grid-template-columns:repeat(2,minmax(0,1fr))'));
assert(css.includes('.main-shell{width:100%;max-width:100%'));
assert(app.includes('window.AutoTraderAudit?.live')===false,"Live hook belongs in local.js");
assert(local.includes('window.AutoTraderAudit?.live'));
assert(app.includes('window.AutoTraderAudit?.robinhood'));
assert(app.includes('window.AutoTraderAudit?.webullTrader'));
assert(app.includes('window.AutoTraderAudit?.paper'));
assert(app.includes('window.AutoTraderAudit?.mask'));
assert(!html.includes("<h1>Live account</h1>"));
assert(!audit.includes('method:"POST"')&&!audit.includes('method:"PUT"')&&!audit.includes('method:"DELETE"'));
const sandbox={
 window:{},document:{addEventListener(){}},
 Date,Intl,Number,String,Array,Math,Object,JSON,Map,Set,Error,console
};
vm.runInNewContext(audit,sandbox,{filename:"ui-audit.js"});
const ui=sandbox.window.AutoTraderAudit;
assert(ui);
assert.equal(ui.mask("112233445566"),"••••5566");
assert.equal(ui.statusText("ARMED_NO_ORDER"),"Armed; no qualifying order");
assert.equal(ui.statusText("TECHNICAL_ONLY_NEWS_OPTIONAL"),"Technical-only news-optional review");
assert.match(ui.moneySigned(0.000117915),/\+\$0\.00011792/);
assert.match(ui.moneySigned(-1.5),/−\$1\.50/);
assert.match(ui.percentSigned(0.5),/\+0\.50%/);
assert.equal(ui.paperTradeRationale({reason:"Shared engine strategy decision"}),
 "Recorded generic strategy rationale; specific signal/model evidence was not linked to this legacy trade");
assert(!ui.time("not a date").includes("Invalid Date"));
console.log("PASS audit UI contracts: broker routes, unique ids, status model, read-only API, risk shells, privacy, timestamps, small P/L");
