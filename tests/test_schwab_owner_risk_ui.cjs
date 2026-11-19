"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=p=>fs.readFileSync(path.join(root,p),"utf8");

test("Schwab has a nine-control live risk interface with explicit capital budget",()=>{
 const html=read("web/index.html");
 const fields=["strategy_capital_usd","allocation_pct","max_order_usd",
 "max_position_pct","max_daily_loss","max_open_positions",
 "max_buys_per_day","max_orders_per_day","daily_growth_target_pct"];
 for(const name of fields){
  assert.match(html,new RegExp('id="live-'+name+'"'),name);
 }
 assert.match(html,/id="live-risk-headroom-preview"/);
 assert.match(html,/min="1" max="30"/);
 assert.doesNotMatch(html,/hard maximum \$25|Hard maximum of three/);
});
test("Schwab UI preview uses verified equity, cash, and remaining exposure",()=>{
 const script=read("web/local.js");
 assert.match(script,/"strategy_capital_usd","allocation_pct"/);
 assert.match(script,/Math\.min\(equity,Math\.max\(0,values\.strategy_capital_usd\)\)/);
 assert.match(script,/capital-exposure/);
 assert.match(script,/cash\*Math\.max\(0,values\.allocation_pct\)\/100/);
 assert.match(script,/live-risk-headroom-preview/);
 assert.doesNotMatch(script,/Math\.min\(25,cash\*allocation/);
 assert.match(script,/increases REAL-MONEY Schwab exposure/);
});
test("Schwab backend no longer uses hidden $25 or 3-position worker cap",()=>{
 const ext=read("app/live_extension.py");
 const worker=read("app/live_worker.py");
 assert.match(ext,/"strategy_capital_usd":\(25,100000\)/);
 assert.match(ext,/"max_open_positions":\(1,30\)/);
 assert.match(worker,/MAX_CONCURRENT_POSITIONS = 30/);
 assert.match(worker,/capital=min\(equity,Decimal\(str\(limits\['strategy_capital_usd'\]\)\)\)/);
 assert.match(worker,/capital_limit=capital if action=="BUY" else CAPITAL/);
 assert.doesNotMatch(worker,/min\(DAILY_LOSS,Decimal\(str\(settings\['max_daily_loss'\]\)\)\)/);
});
