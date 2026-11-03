"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const source=fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
const nodes=new Map();
const make=(id)=>{
  const classes=new Set();
  return {id,textContent:"",title:"",classList:{
    add:(...keys)=>keys.forEach(k=>classes.add(k)),
    remove:(...keys)=>keys.forEach(k=>classes.delete(k)),
    toggle:(key,force)=>force===true?classes.add(key):force===false?classes.delete(key):classes.has(key)?classes.delete(key):classes.add(key)
  }};
};
for(const name of ["workspace-robinhood-balance","workspace-robinhood-value-note",
  "workspace-robinhood-status","workspace-robinhood-agent","workspace-active-count"]){
  nodes.set(name,make(name));
}
const context=vm.createContext({
  console,Intl,Date,Number,String,Object,Error,Math,
  document:{getElementById:id=>nodes.get(id)||null,
    querySelector:()=>null,querySelectorAll:()=>[],addEventListener:()=>{}}
});
vm.runInContext(source+"\nglobalThis.__rh={updateRobinhoodTile,updateRobinhoodTilePortfolio,clearWorkspaceBalances,refreshRobinhoodTile};",context);
const {updateRobinhoodTile,updateRobinhoodTilePortfolio,clearWorkspaceBalances,refreshRobinhoodTile}=context.__rh;
const amount=nodes.get("workspace-robinhood-balance"),note=nodes.get("workspace-robinhood-value-note");
const authenticated={connected:true,credentials_saved:true,
  accounts:[{buying_power:"22.05",buying_power_currency:"USD",is_api_tradable:true}]};
updateRobinhoodTile(authenticated);
assert.equal(amount.textContent,"Checking account value…");
updateRobinhoodTilePortfolio({available:true,estimated_crypto_account_value_usd:"53.62"});
assert.equal(amount.textContent,"$53.62");
assert.match(note.textContent,/Holdings \+ USD buying power/);
assert.doesNotMatch(amount.title,/buying power; this is not total portfolio equity/);
updateRobinhoodTilePortfolio({available:true,estimated_crypto_account_value_usd:"0"});
assert.equal(amount.textContent,"$0.00");
for(const raw of [null,undefined,"",NaN,0,"-1","NaN","Infinity","53.62USD","1000000000001"]){
  updateRobinhoodTilePortfolio({available:true,estimated_crypto_account_value_usd:raw});
  assert.equal(amount.textContent,"Account value unavailable",String(raw));
}
updateRobinhoodTilePortfolio({available:true,estimated_crypto_account_value_usd:null,
  cash_usd:"22.05",known_holdings_value_usd:"31.57",unpriced_holdings:["DOGE-USD"]});
assert.equal(amount.textContent,"Account value unavailable");
assert.match(note.textContent,/lack verified quotes/);
updateRobinhoodTilePortfolio({available:false,reason:"Broker connection failed"});
assert.equal(amount.textContent,"Account value unavailable");
async function run(){
  let calls=[];
  context.fetch=async url=>{
    calls.push(url);
    return {ok:true,status:200,json:async()=>url==="/api/robinhood/status"?
      authenticated:{available:true,estimated_crypto_account_value_usd:"53.62"}};
  };
  await refreshRobinhoodTile();
  assert.equal(amount.textContent,"$53.62");
  assert.deepEqual(calls,["/api/robinhood/status","/api/robinhood/portfolio"]);
  calls=[];
  context.fetch=async url=>{
    calls.push(url);
    return {ok:true,status:200,json:async()=>({connected:false,credentials_saved:true,accounts:[]})};
  };
  await refreshRobinhoodTile();
  assert.equal(amount.textContent,"Account value unavailable");
  assert.deepEqual(calls,["/api/robinhood/status"]);
  let finish;
  context.fetch=async url=>{
    if(url==="/api/robinhood/status")return {ok:true,status:200,json:async()=>authenticated};
    return new Promise(resolve=>{finish=()=>resolve({ok:true,status:200,
      json:async()=>({available:true,estimated_crypto_account_value_usd:"53.62"})});});
  };
  const pending=refreshRobinhoodTile();
  for(let i=0;i<8&&!finish;i++)await Promise.resolve();
  assert.equal(typeof finish,"function");
  clearWorkspaceBalances();
  finish();
  await pending;
  assert.equal(amount.textContent,"Account value unavailable");
  console.log("PASS: Robinhood account overview uses verified portfolio total, never buying power alone; unavailable and logout paths safe");
}
run().catch(e=>{console.error(e);process.exitCode=1;});
