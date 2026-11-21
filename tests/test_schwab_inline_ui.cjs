"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const root=path.resolve(__dirname,"..");
const read=p=>fs.readFileSync(path.join(root,p),"utf8");

class Element {
  constructor(tag){
    this.tagName=tag;this.children=[];this.className="";
    this.textContent="";this.id="";this.value="";this.disabled=false;
    this.listeners={};this.attributes={};
    this.classList={
      add:label=>this._class(label,true),
      remove:label=>this._class(label,false),
      toggle:(label,force)=>{
        const on=force===undefined?!this.className.split(" ").includes(label):force;
        this._class(label,on);return on;
      },
      contains:label=>this.className.split(" ").includes(label)
    };
  }
  _class(label,enabled){
    const parts=new Set(this.className.split(" ").filter(Boolean));
    if(enabled)parts.add(label);else parts.delete(label);
    this.className=[...parts].join(" ");
  }
  append(...children){this.children.push(...children);}
  appendChild(child){this.append(child);return child;}
  replaceChildren(...children){this.children=children;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  setAttribute(name,value){this.attributes[name]=value;}
  removeAttribute(name){delete this.attributes[name];if(name==="href")this.href="";}
  get options(){return this.children.filter(c=>c.tagName==="option");}
}
function deepFind(el,id){
  if(el.id===id)return el;
  for(const child of el.children){
    const found=deepFind(child,id);if(found)return found;
  }
  return null;
}
function harness(){
  const grid=new Element("div"), status=new Element("p");
  const calls=[],auths=[];
  let liveState={auth_state:"REAUTH_REQUIRED",worker_supervisor:{state:"REAUTH_REQUIRED"},
    worker_online:false,order_permission:"paused"};
  let changedLive=false;
  const fakeResponses={
    "/api/brokers":{schema:1,brokers:[{
      id:"schwab",name:"Charles Schwab",description:"Broker stocks",
      integration_status:"authorization_saved",app_account_connected:true,
      app_orders_supported:true,docs_url:"https://developer.schwab.com",
      auth_method:"OAuth2",assets:["Stocks"],setup_requirement:"Authorization required"
    }]},
    "/api/integrations":{schwab_app_key:"APP-KEY",schwab_secret_set:true,
      schwab_token_connected:true,schwab_callback_url:"https://127.0.0.1:8182"},
    "/api/schwab/connect":{authorization_url:
      "https://api.schwabapi.com/v1/oauth/authorize?client_id=FAKE",
      automatic_callback:false,instructions:"Paste full callback URL",resumed:false},
    "/api/schwab/accounts":{accounts:[{hash:"VALID_HASH",label:"Account ending 1234"}]},
    "/api/live/activation":{live_enabled:true},
    "/api/schwab/complete":{connected:true,accounts_verified:true}
  };
  const request=async(url,opts={})=>{
    calls.push([url,opts]);
    if(url==="/api/live")return liveState;
    if(url==="/api/schwab/complete"){
      liveState={auth_state:"AWAITING_WORKER_VERIFICATION",
        worker_supervisor:{state:"STARTING"},worker_online:false,order_permission:"paused"};
    }
    if(!(url in fakeResponses))throw Error("Unexpected route: "+url);
    return fakeResponses[url];
  };
  const document={
    createElement:tag=>new Element(tag),
    getElementById:id=>id==="broker-grid"?grid:id==="brokers-status"?status:null,
    addEventListener:()=>{}
  };
  const window={confirm:message=>{auths.push(message);return true;}};
  const sandbox={request,document,window,URL,console};
  vm.runInNewContext(read("web/brokers.js"),sandbox);
  const get=id=>deepFind(grid,id);
  return {get,calls,auths,grid,status,load:sandbox.loadBrokerWorkspace};
}
test("Broker connections is directly under Account overview and appears only once",()=>{
  const html=read("web/index.html");
  const start=html.indexOf('data-view="workspaces"');
  const broker=html.indexOf('data-view="brokers"');
  const shared=html.indexOf('id="overview-shared-nav"');
  assert.ok(start>=0&&broker>start&&broker<shared);
  const sidebar=html.slice(html.indexOf('<aside class="sidebar">'),html.indexOf('<div class="main-shell">'));
  assert.equal((sidebar.match(/data-view="brokers"/g)||[]).length,1);
  assert.match(read("web/unified.js"),/showView\("brokers"\)/);
});
test("Saved expired authorization offers ONE inline Connect / Reconnect action",async()=>{
  const h=harness();
  await h.load();
  await new Promise(setImmediate);
  assert.match(h.get("schwab-inline-status").textContent,/expired or was revoked/);
  assert.equal(h.get("schwab-inline-connect").disabled,false);
  assert.ok(h.get("schwab-inline-settings"));
  assert.ok(h.get("schwab-inline-account"));
  await h.get("schwab-inline-connect").listeners.click();
  assert.equal(h.calls.filter(x=>x[0]==="/api/schwab/connect").length,1);
  assert.equal(h.calls.find(x=>x[0]==="/api/schwab/connect")[1].body,"{}");
  assert.match(h.get("schwab-inline-oauth-link").href,/^https:\/\/api\.schwabapi\.com/);
  assert.equal(h.auths.length,0);
  assert.equal(h.get("schwab-inline-callback-form").classList.contains("hidden"),false);
});
test("User may explicitly restart OAuth without changing any trading permission",async()=>{
  const h=harness();
  await h.load();await new Promise(setImmediate);
  await h.get("schwab-inline-connect").listeners.click();
  await h.get("schwab-inline-restart").listeners.click();
  const calls=h.calls.filter(x=>x[0]==="/api/schwab/connect");
  assert.equal(calls.length,2);
  assert.equal(calls[1][1].body,JSON.stringify({restart:true}));
  assert.equal(h.calls.some(x=>x[0]==="/api/live/activation"),false);
});
test("Manual callback finishes via authenticated API; verification never silently enables orders",async()=>{
  const h=harness();
  await h.load();await new Promise(setImmediate);
  await h.get("schwab-inline-connect").listeners.click();
  h.get("schwab-inline-redirect").value="https://127.0.0.1:8182/?code=FAKE&state=EXAMPLE";
  await h.get("schwab-inline-callback-form").listeners.submit({preventDefault(){}});
  const end=h.calls.find(x=>x[0]==="/api/schwab/complete");
  assert.ok(end);
  assert.match(end[1].body,/redirected_url/);
  assert.equal(h.calls.some(x=>x[0]==="/api/live/activation"),false);
  assert.equal(h.get("schwab-inline-redirect").value,"");
});
test("Live order permission needs explicit fresh account verification and confirmation",async()=>{
  const h=harness();
  await h.load();await new Promise(setImmediate);
  const section=h.get("schwab-inline-account").children;
  assert.equal(h.get("schwab-inline-account").options.length,0);
  assert.equal(h.calls.some(x=>x[0]==="/api/live/activation"),false);
  const buttons=h.grid.children.flatMap(()=>[]);
  // Buttons live inside the account details; select's parent-level lookup
  // controls can be located by their visible text.
  function byText(node,text){
    if(node.textContent===text&&node.tagName==="button")return node;
    for(const n of node.children){const x=byText(n,text);if(x)return x;}
    return null;
  }
  await byText(h.grid,"Verify Schwab accounts").listeners.click();
  assert.equal(h.get("schwab-inline-account").options.length,1);
  h.get("schwab-inline-account").value="VALID_HASH";
  await byText(h.grid,"Enable live Schwab orders").listeners.click();
  assert.equal(h.auths.length,1);
  const request=h.calls.find(x=>x[0]==="/api/live/activation");
  assert.ok(request);
  assert.equal(JSON.parse(request[1].body).account_hash,"VALID_HASH");
});
