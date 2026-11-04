"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const html=fs.readFileSync(path.join(__dirname,"../web/index.html"),"utf8");
const app=fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
const local=fs.readFileSync(path.join(__dirname,"../web/local.js"),"utf8");
assert.equal((html.match(/id="ai-header-status"/g)||[]).length,1);
assert.equal((html.match(/id="ai-header-model"/g)||[]).length,1);
assert.match(html,/id="refresh-btn"[^>]*aria-label="Refresh current screen"/);
for(const id of ["live-current-model","live-local-inference","robinhood-ai-readiness"]){
  assert(!html.includes('id="'+id+'"'),"Duplicate trade model status: "+id);
  assert(!app.includes('$("'+id+'")')&&!local.includes('$("'+id+'")'));
}
assert(!html.includes("Shared Â· Account Overview â†’ AI workstation models"),
  "Shared model controls should not be repeated in broker windows");
assert.match(html,/id="local-model-form"/,"Dedicated shared AI setup is preserved");
assert.match(html,/id="robinhood-ai-decisions"/,"Decision evidence remains available");
assert.match(html,/id="live-decisions-table"/,"Schwab historical evidence preserved");
const nodes={};
const node=()=>({
  textContent:"",title:"",disabled:false,attributes:{},
  classList:{
    values:new Set(),
    add(...a){for(const x of a)this.values.add(x)},
    remove(...a){for(const x of a)this.values.delete(x)},
    toggle(x,yes){if(yes)this.values.add(x);else this.values.delete(x)},
    contains(x){return this.values.has(x)}
  },
  setAttribute(k,v){this.attributes[k]=String(v)},
  removeAttribute(k){delete this.attributes[k]}
});
for(const k of ["ai-header-status","ai-header-state","ai-header-model","refresh-btn"])nodes[k]=node();
const context=vm.createContext({
  console,Math,Date,Number,String,Intl,Object,Promise,JSON,Error,
  document:{readyState:"loading",getElementById:id=>nodes[id]||null,
    addEventListener(){},querySelectorAll(){return[]},querySelector(){return null}}
});
vm.runInContext(app+String.raw`
globalThis.__ui={renderAIHeader,refreshAIHeader,refreshCurrentScreen,currentViewRefreshJobs};
globalThis.__auth=(value)=>csrf=value;
globalThis.__view=(value)=>activeView=value;
`,context);
const ui=context.__ui;
for(const dependency of ["loadLocalModels","loadBrokerWorkspace","loadForecast"]) context[dependency]=async()=>{};
ui.renderAIHeader({provider:"ollama",model:"qwen3.5:4b",
 status:"metadata_verified",connection_tested:true,capability_tested:false});
assert.equal(nodes["ai-header-state"].textContent,"AI online");
assert.equal(nodes["ai-header-model"].textContent,"qwen3.5:4b");
assert(nodes["ai-header-status"].classList.contains("is-online"));
assert.match(nodes["ai-header-status"].title,/Inference capability is not verified/);
ui.renderAIHeader({provider:"ollama",model:"qwen3.5:4b",
 status:"unavailable_or_invalid_metadata",connection_tested:false});
assert.equal(nodes["ai-header-state"].textContent,"AI offline");
assert(nodes["ai-header-status"].classList.contains("is-offline"));
ui.renderAIHeader({provider:"none",status:"not_configured",model:""});
assert.equal(nodes["ai-header-state"].textContent,"AI not configured");
ui.renderAIHeader({provider:"ollama",model:"<script>",
 status:"metadata_verified",connection_tested:true});
assert.equal(nodes["ai-header-model"].textContent,"No verified model selection");
ui.renderAIHeader({provider:"chatgpt-oauth",model:"gpt-test",status:"needs_runtime_verification",connection_tested:false});
assert.equal(nodes["ai-header-state"].textContent,"AI unverified");
const routes={
  workspaces:["workspace availability","Robinhood overview","Webull overview"],
  robinhood:["Robinhood dashboard"],
  "robinhood-risk":["Robinhood risk controls"],
  "robinhood-decisions":["Robinhood decisions"],
  "robinhood-forecast":["Robinhood forecast"],
  webull:["Webull dashboard"],
  "webull-risk":["Webull risk controls"],
  "webull-decisions":["Webull decisions"],
  "webull-orders":["Webull orders"],
  operations:["Trading operations"],
  local:["AI workstation models"],
  brokers:["Broker connections"],
  forecast:["Market forecast"],
  profile:["Profile","Webull account preference"],
  live:[],
  "live-risk":[],
  overview:[],
  trades:[],
  reviews:[],
  settings:["Paper service"]
};
for(const [view,expected] of Object.entries(routes)){
  const labels=Array.from(ui.currentViewRefreshJobs(view),x=>x[0]);
  assert.deepEqual(labels,expected,"refresh routing "+view);
}
async function run(){
  context.request=async url=>{
    assert.equal(url,"/api/ai/readiness");
    return {provider:"ollama",model:"qwen3.5:4b",
      status:"metadata_verified",connection_tested:true,capability_tested:false};
  };
  context.__auth("session");
  await ui.refreshAIHeader();
  assert.equal(nodes["ai-header-model"].textContent,"qwen3.5:4b");
  context.request=async()=>{throw Error("DNS unavailable")};
  await assert.rejects(ui.refreshAIHeader(),/DNS unavailable/);
  assert.equal(nodes["ai-header-state"].textContent,"AI offline");
  // All required manual refresh actions complete before the button releases.
  const called=[];
  vm.runInContext(String.raw`
    toast=(message,error)=>globalThis.__messages.push({message,error});
    refreshAll=async()=>globalThis.__called.push("summary");
    refreshVerifiedConnectedAccounts=async()=>globalThis.__called.push("brokers");
    refreshAIHeader=async()=>globalThis.__called.push("ai");
    loadWebullOrders=async()=>globalThis.__called.push("webull orders");
    loadRobinhoodWorkspace=async()=>globalThis.__called.push("robinhood");
  `,context);
  context.__called=called;context.__messages=[];
  context.__view("webull-orders");
  await ui.refreshCurrentScreen();
  assert.deepEqual(called,["summary","brokers","ai","webull orders"]);
  assert.equal(nodes["refresh-btn"].disabled,false);
  assert.equal(nodes["refresh-btn"].attributes["aria-busy"],undefined);
  assert.equal(context.__messages[0].error,undefined);
  called.length=0;context.__messages.length=0;
  context.__view("robinhood");
  await ui.refreshCurrentScreen();
  assert.deepEqual(called,["summary","brokers","ai","robinhood"]);
  // Partial failures must be surfaced, not falsely claim success.
  context.__view("webull-orders");
  vm.runInContext('loadWebullOrders=async()=>{throw Error("webull unavailable")};',context);
  context.__messages.length=0;
  await ui.refreshCurrentScreen();
  assert.match(context.__messages[0].message,/Refresh incomplete.*Webull orders/);
  assert.equal(context.__messages[0].error,true);
  assert.equal(nodes["refresh-btn"].disabled,false);
  console.log("PASS: model identity, true reachability, explicit offline state, per-view manual refresh and error visibility");
}
run().catch(err=>{console.error(err);process.exitCode=1});
