/* Browserless tests for tile equity: never show stale/unverified balances. */
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const elements={};
for(const key of ["workspace-schwab-balance","workspace-paper-balance"]){
  elements[key]={textContent:"",title:""};
}
const context={
  console,Intl,Date,Number,String,Object,Error,Math,
  document:{
    getElementById:(id)=>elements[id]||null,
    addEventListener:()=>{}
  }
};
const code=fs.readFileSync(path.resolve(__dirname,"../web/app.js"),"utf8");
vm.runInNewContext(code+"\nglobalThis.__balances={updateWorkspaceBalances,clearWorkspaceBalances};",context);
const {updateWorkspaceBalances,clearWorkspaceBalances}=context.__balances;
const paper=elements["workspace-paper-balance"];
const live=elements["workspace-schwab-balance"];
const now=new Date().toISOString();
updateWorkspaceBalances({account:{equity:15234.5}},{worker_online:true,account:{at:now,equity:23500.25}});
assert.equal(paper.textContent,"Sim. equity $15,234.50");
assert.equal(live.textContent,"Equity $23,500.25");
updateWorkspaceBalances({account:{equity:0}},{worker_online:false,account:{at:now,equity:23500.25}});
assert.equal(paper.textContent,"Sim. equity $0.00"); // explicit real simulator zero, not guessed
assert.equal(live.textContent,"Balance unavailable");
updateWorkspaceBalances({account:{}},{worker_online:true,account:{at:new Date(Date.now()-3600000).toISOString(),equity:23500.25}});
assert.equal(paper.textContent,"Balance unavailable");
assert.equal(live.textContent,"Balance unavailable");
updateWorkspaceBalances({account:{equity:"500000.00"}},{worker_online:true,account:{at:now,equity:"25000.00"}});
assert.equal(paper.textContent,"Balance unavailable");
assert.equal(live.textContent,"Balance unavailable");
updateWorkspaceBalances({account:{equity:-130.25}},{worker_online:true,account:{at:now,equity:-650.11}});
assert.equal(paper.textContent,"Sim. equity -$130.25");
assert.equal(live.textContent,"Equity -$650.11");
clearWorkspaceBalances();
assert.equal(paper.textContent,"Balance unavailable");
assert.equal(live.textContent,"Balance unavailable");
console.log("PASS: account tile balances distinguish fresh equity, unavailable, stale, invalid, zero and logout states");
