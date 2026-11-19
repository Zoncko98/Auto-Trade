"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=p=>fs.readFileSync(path.join(root,p),"utf8");

test("all four trader dashboards use one shared visible layout and compact navigation",()=>{
  const html=read("web/index.html");
  const js=read("web/unified.js");
  const css=read("web/unified.css");
  const server=read("app/dashboard_server.py");
  for(const [key,id] of [["live","live"],["robinhood","robinhood"],["webull","webull"],["paper","overview"]]){
    assert.match(html,new RegExp('id="view-'+id+'".*data-broker-dashboard='));
    assert.match(js,new RegExp('(?:^|\\n)    '+key+':\\{'));
  }
  assert.match(js,/setupDashboard\(key,cfg\);setupRiskGuide\(key,cfg\)/);
  assert.match(js,/disclosure\("Execution status & account details"/);
  assert.match(js,/disclosure\("Activity, strategy diagnostics & records"/);
  assert.match(js,/disclosure\("View current holdings"/);
  assert.match(js,/navButton\("Risk & start"/);
  assert.match(js,/navButton\("Orders & activity"/);
  assert.match(css,/max-width:600px/);
  assert.match(css,/:focus-visible/);
  assert.match(html,/\/unified\.css/);
  assert.match(html,/\/unified\.js/);
  assert.match(server,/"\/unified\.js": \("unified\.js"/);
  assert.match(server,/"\/unified\.css": \("unified\.css"/);
});
test("live start preserves explicit confirmation and CSRF request helpers",()=>{
  const ui=read("web/unified.js");
  assert.match(ui,/window\.confirm\("Start autonomous Robinhood crypto trading with REAL MONEY/);
  assert.match(ui,/window\.confirm\("Start autonomous Schwab trading with REAL MONEY/);
  assert.match(ui,/webullChangePermission\(true\)/);
  assert.match(ui,/const state=await request\("\/api\/webull\/trader"\)/);
  assert.match(ui,/policy:\{\.\.\.current\.policy,enabled:false\}/);
  assert.match(ui,/if\(current\.journal_halted\)/);
  assert.match(ui,/if\(policy\.configured!==true\|\|!policy\.account\)/);
});
test("runtime order gates still exist after reducing arm-only Webull restrictions",()=>{
  const server=read("app/dashboard_server.py");
  const worker=read("app/webull_worker.py");
  const gate=worker.slice(worker.indexOf("def _live_gate("),worker.indexOf("def ",worker.indexOf("def _live_gate(")+5));
  assert.match(gate,/journal\.pending\(account_id\)/);
  assert.match(gate,/broker\.open_orders\(account_id\)/);
  assert.match(gate,/broker\.balance\(account_id\)/);
  assert.match(gate,/verify_margin_cash_funding/);
  assert.match(gate,/max_daily_loss_usd/);
  assert.match(gate,/max_open_positions/);
  assert.match(server,/Emergency pause must work even if the broker API is offline/);
  assert.match(server,/Pausing is a local kill-switch and must work offline/);
});
