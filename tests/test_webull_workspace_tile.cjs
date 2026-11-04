"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
const start=source.indexOf("function webullAccountVerified(data){");
const end=source.indexOf("function positionRobinhoodTile(configured){",start);
assert(start>=0&&end>start,"Webull rendering functions exist");
const snippet=source.slice(start,end);
function classes(){
  const vals=new Set(["workspace-tile","workspace-tile-compact"]);
  return {contains:k=>vals.has(k),toggle:(k,v)=>v?vals.add(k):vals.delete(k)};
}
const active={children:[],appendChild(tile){if(tile.parentElement)tile.parentElement.children=tile.parentElement.children.filter(x=>x!==tile);this.children.push(tile);tile.parentElement=this;}};
const upcoming={children:[],appendChild:active.appendChild};
const label={hidden:true},status={textContent:""},main={textContent:""},detail={textContent:""},count={textContent:""};
const tile={parentElement:null,classList:classes(),title:"",
   attributes:{},setAttribute(k,v){this.attributes[k]=v;},
   querySelector(k){return k===".workspace-tile-equity-label"?label:null;}};
upcoming.appendChild(tile);
const elems={"workspace-webull-status":status,"workspace-webull-balance":main,
             "workspace-webull-detail":detail,"workspace-active-count":count};
const document={
  querySelector(k){
    return k==='[data-workspace="webull"]'?tile:
      k===".workspace-tile-grid"?active:
      k===".workspace-upcoming-grid"?upcoming:null;
  },
  getElementById:k=>elems[k]??null,
  querySelectorAll(k){
    assert.equal(k,".workspace-tile-grid .workspace-tile:not(.is-coming-soon)");
    return [{},{},...active.children];
  }
};
let nextStatus=null;
const ctx={document,console,request:async()=>nextStatus};
vm.runInNewContext('const csrf="verified"; let webullTileRefreshId=0; const $=id=>document.getElementById(id);'+snippet+
'globalThis.testApi={webullAccountVerified,updateWebullTile,refreshWebullTile};',ctx);
const {webullAccountVerified,updateWebullTile,refreshWebullTile}=ctx.testApi;
const ready={connected:true,credentials_saved:true,environment:"production",
             accounts:[{account_id:"CASH123",account_type:"INDIVIDUAL_CASH"},
                       {account_id:"MARGIN123",account_type:"INDIVIDUAL_MARGIN"},
                       {account_id:"CRYPTO123",account_type:"CRYPTO"}],
             selected_stock_account:"MARGIN123",
             operator_live_policy_armed:true,execution_enabled:true};
assert.equal(webullAccountVerified({connected:true,accounts:[]}),false);
assert.equal(webullAccountVerified({credentials_saved:true,connected:false,accounts:ready.accounts}),false);
updateWebullTile({credentials_saved:true,connected:false,accounts:ready.accounts});
assert.equal(tile.parentElement,upcoming,"Credentials alone never promote the tile");
assert.match(status.textContent,/VERIFY/);
assert.equal(label.hidden,true);
assert.equal(count.textContent,"● 2 available");
updateWebullTile(ready);
assert.equal(tile.parentElement,active,"Authenticated account promotes tile");
assert.equal(tile.classList.contains("workspace-tile-featured"),true);
assert.equal(label.hidden,false);
assert.equal(status.textContent,"STOCK LIVE POLICY ARMED");
assert.match(main.textContent,/1 trading account/);
assert.match(detail.textContent,/live policy armed/);
assert.doesNotMatch(detail.textContent,/CASH123/);
assert.equal(count.textContent,"● 3 available");
assert.match(tile.attributes["aria-label"],/verified Webull account/);
// A linked cash-only account must not be treated as a selectable Webull
// trading account or used in the aggregate equity valuation.
updateWebullTile({...ready,accounts:[ready.accounts[0]],
  selected_stock_account:"",operator_live_policy_armed:false});
assert.match(main.textContent,/0 trading accounts/);
updateWebullTile({...ready,environment:"sandbox"});
assert.match(status.textContent,/SANDBOX/);
updateWebullTile({connected:false,credentials_saved:true});
assert.equal(tile.parentElement,upcoming,"Lost authentication demotes tile");
assert.equal(tile.classList.contains("workspace-tile-featured"),false);
assert.equal(label.hidden,true);
(async()=>{
  nextStatus=ready;
  await refreshWebullTile();
  assert.equal(tile.parentElement,active,"Background refresh promotes account");
  nextStatus={connected:false,credentials_saved:true};
  await refreshWebullTile();
  assert.equal(tile.parentElement,upcoming,"Background refresh removes unverified account");
  console.log("Webull active account tile transitions verified");
})().catch(error=>{console.error(error);process.exitCode=1});
