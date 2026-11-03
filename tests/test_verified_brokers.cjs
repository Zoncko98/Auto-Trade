"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const html=fs.readFileSync(path.join(__dirname,"../web/index.html"),"utf8");
const js=fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
const local=fs.readFileSync(path.join(__dirname,"../web/local.js"),"utf8");
const sidebar=html.split('<aside class="sidebar">')[1].split("</aside>")[0];
assert.match(sidebar,/id="verified-brokers"/);
assert.match(sidebar,/CONNECTED ACCOUNTS/);
assert(!sidebar.includes('id="side-live-status"'));
assert(!sidebar.includes('id="ai-readiness-indicator"'));
assert(!html.includes('id="server-pill"'));
assert(!html.includes('class="workspace-command-strip"'));
assert(!html.includes('id="workspace-active-count"'));
assert(!local.includes('server-pill')&&!local.includes('side-live-status'));
const nodes={};
const classSet=()=>{const s=new Set(["hidden"]);return {contains:x=>s.has(x),
  add:x=>s.add(x),remove:x=>s.delete(x),toggle:(x,on)=>{on?s.add(x):s.delete(x)}};};
const elem=()=>({textContent:"",title:"",className:"",children:[],
  setAttribute(){},append(...children){this.children.push(...children)},
  replaceChildren(){this.children=[]},classList:classSet()});
nodes["verified-brokers"]=elem();
nodes["verified-broker-items"]=elem();
const context={console,Intl,Date,Number,String,Object,Math,Error,Promise,
 document:{getElementById:id=>nodes[id]||null,createElement:()=>elem(),addEventListener(){}},
 setInterval(){}};
vm.runInNewContext(js+"\nglobalThis.__test={verifiedConnectedAccounts,renderVerifiedConnectedAccounts,refreshVerifiedConnectedAccounts,clearVerifiedConnectedAccounts};csrf='authenticated';",context);
const api=context.__test;
const now=new Date().toISOString();
const goodSchwab={worker_online:true,heartbeat_age_sec:23,account:{at:now,equity:"3520.50"}};
const goodRobinhood={connected:true,accounts:[{account_number:"acct-123",status:"active",is_api_tradable:false}]};
const goodWebull={connected:true,environment:"production",accounts:[{account_id:"acct-456"}]};
const labels=(...values)=>Array.from(api.verifiedConnectedAccounts(...values),r=>r.name);
assert.deepEqual(labels(goodSchwab,goodRobinhood,goodWebull),["Schwab","Robinhood Crypto","Webull"]);
assert.deepEqual(labels({worker_online:true,heartbeat_age_sec:2,account:{at:now,equity:0}},null,null),["Schwab"]);
assert.deepEqual(labels({worker_online:false,heartbeat_age_sec:30,account:{at:now,equity:100}},null,null),[]);
assert.deepEqual(labels({worker_online:true,heartbeat_age_sec:121,account:{at:now,equity:100}},null,null),[]);
assert.deepEqual(labels({worker_online:true,heartbeat_age_sec:2,account:{at:new Date(Date.now()-3600000).toISOString(),equity:100}},null,null),[]);
assert.deepEqual(labels({worker_online:true,heartbeat_age_sec:2,account:{at:now,equity:"NaN"}},null,null),[]);
assert.deepEqual(labels(null,{credentials_saved:true,connected:false,accounts:goodRobinhood.accounts},null),[]);
assert.deepEqual(labels(null,{connected:true,accounts:[]},null),[]);
assert.deepEqual(labels(null,{connected:true,accounts:[{account_number:"",status:"active"}]},null),[]);
assert.deepEqual(labels(null,{connected:true,accounts:[{account_number:"acct",status:"inactive"}]},null),[]);
assert.deepEqual(labels(null,null,{connected:true,accounts:[{account_id:""}]}),[]);
assert.deepEqual(labels(null,null,{credentials_saved:true,connected:false,accounts:goodWebull.accounts}),[]);
assert.deepEqual(labels(null,null,{connected:true,environment:"sandbox",accounts:[{account_id:"id1"}]}),["Webull (sandbox)"]);
api.renderVerifiedConnectedAccounts(api.verifiedConnectedAccounts(goodSchwab,goodRobinhood,goodWebull));
assert.equal(nodes["verified-brokers"].classList.contains("hidden"),false);
assert.equal(nodes["verified-broker-items"].children.length,3);
const text=nodes["verified-broker-items"].children.map(x=>x.children[1].textContent);
assert.deepEqual(text,["Schwab","Robinhood Crypto","Webull"]);
assert(!JSON.stringify(nodes["verified-broker-items"].children.map(x=>x.children[1].textContent)).includes("acct-"));
async function run(){
 context.request=async uri=>({
  "/api/live":goodSchwab,"/api/robinhood/status":goodRobinhood,"/api/webull/status":goodWebull
 })[uri];
 await api.refreshVerifiedConnectedAccounts();
 assert.equal(nodes["verified-broker-items"].children.length,3);
 context.request=async()=>{throw Error("No verified connection");};
 await api.refreshVerifiedConnectedAccounts();
 assert.equal(nodes["verified-broker-items"].children.length,0);
 assert(nodes["verified-brokers"].classList.contains("hidden"));
 const releases=[];
 context.request=async()=>new Promise(resolve=>{releases.push(()=>resolve(goodSchwab))});
 const pending=api.refreshVerifiedConnectedAccounts();
 api.clearVerifiedConnectedAccounts();
 assert.equal(releases.length,3);
 releases.forEach(release=>release());
 await pending;
 assert(nodes["verified-brokers"].classList.contains("hidden"),"logout must discard pending responses");
 context.request=async uri=>uri==="/api/live"?goodSchwab:Promise.reject(Error("broker unavailable"));
 await api.refreshVerifiedConnectedAccounts();
 assert.deepEqual(nodes["verified-broker-items"].children.map(x=>x.children[1].textContent),["Schwab"]);
 console.log("PASS: upper-left only shows verified accounts; missing/stale/sandbox/logout/failure safe");
}
run().catch(err=>{console.error(err);process.exitCode=1});
