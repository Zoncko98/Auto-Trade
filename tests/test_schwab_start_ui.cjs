"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const root=path.resolve(__dirname,"..");
const read=p=>fs.readFileSync(path.join(root,p),"utf8");

function loadUnified(){
  const buttons=[{dataset:{unifiedAction:"start",account:"live"},textContent:"Start trading"},
                 {dataset:{unifiedAction:"start",account:"live"},textContent:"Start trading"},
                 {dataset:{unifiedAction:"start",account:"robinhood"},textContent:"Start trading"}];
  const classes=new Set();
  const feedback={textContent:"",classList:{
    add:name=>classes.add(name),remove:name=>classes.delete(name),
    toggle:(name,on)=>on?classes.add(name):classes.delete(name)}};
  const hint={textContent:""};
  const status={textContent:"Offline"};
  const document={
    readyState:"loading",
    addEventListener:()=>{},
    querySelectorAll:selector=>{
      assert.match(selector,/view-live/);
      return buttons;
    },
    getElementById:id=>{
      if(id==="unified-feedback-live")return feedback;
      if(id==="view-live-risk")return {querySelector:()=>hint};
      if(id==="live-worker-mode")return status;
      return null;
    }
  };
  const window={};
  vm.runInNewContext(read("web/unified.js"),{document,window});
  return {unified:window.AutoTraderUnified,buttons,feedback,hint,classes};
}

test("expired Schwab OAuth labels both workspace start actions as explicit reconnection",()=>{
  const x=loadUnified();
  x.unified.setSchwabStatus({auth_state:"REAUTH_REQUIRED",
    worker_supervisor:{state:"REAUTH_REQUIRED"}});
  for(const button of x.buttons.slice(0,2)){
    assert.equal(button.dataset.unifiedAction,"reconnect");
    assert.equal(button.textContent,"Reconnect Schwab");
    assert.match(button.title,/OAuth reconnection/);
  }
  assert.equal(x.buttons[2].dataset.unifiedAction,"start");
  assert.match(x.feedback.textContent,/authorization expired/);
  assert.match(x.hint.textContent,/sign-in/);
  assert.equal(x.classes.has("is-error"),true);
});

test("successful recovery restores explicit Start trading action without auto-arming",()=>{
  const x=loadUnified();
  x.unified.setSchwabStatus({auth_state:"REAUTH_REQUIRED"});
  x.unified.setSchwabStatus({auth_state:"WORKER_VERIFIED",
    worker_supervisor:{state:"RUNNING"}});
  for(const button of x.buttons.slice(0,2)){
    assert.equal(button.dataset.unifiedAction,"start");
    assert.equal(button.textContent,"Start trading");
  }
  assert.equal(x.classes.has("is-error"),false);
  assert.match(x.hint.textContent,/Start when the account is authorized/);
});

test("Schwab Start never silently navigates, but explicit Reconnect opens Schwab OAuth page",()=>{
  const js=read("web/unified.js");
  const start=js.slice(js.indexOf('async function start(key)'),
                       js.indexOf('if(key==="robinhood")',js.indexOf('async function start(key)')));
  assert.doesNotMatch(start,/showView\("brokers"\)/);
  assert.match(start,/current\.auth_state==="REAUTH_REQUIRED"/);
  assert.match(start,/if\(!current\.worker_online\|\|!current\.armed\)/);
  assert.match(start,/window\.confirm\("Start autonomous Schwab trading with REAL MONEY/);
  assert.match(js,/button\.dataset\.unifiedAction==="reconnect"&&key==="live"/);
  assert.match(js,/window\.location\.assign\("\/broker-schwab\.html#schwab-onboarding"\)/);
  assert.match(read("web/broker-schwab.html"),/id="schwab-onboarding"/);
  assert.match(read("web/local.js"),/setSchwabStatus\(data\)/);
  assert.match(read("app/live_dashboard.py"),/authorization_blocked=reauth_required\(state_dir\)/);
  assert.match(read("app/dashboard_server.py"),/OAuth reauthorization required/);
});
