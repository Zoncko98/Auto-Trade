"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const html=fs.readFileSync(path.join(__dirname,"../web/index.html"),"utf8");
const js=fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
for(const id of ["rh-fee-summary-overview","rh-fee-shadow-diagnostics",
  "rh-fee-count","rh-fee-shadow","rh-fee-candidates","rh-fee-positions","rh-fee-exits"]){
    assert.ok(html.includes('id="'+id+'"'),"missing evidence UI "+id);
}
assert.ok(js.includes('"/api/robinhood/strategy-diagnostics"'),
  "diagnostic API must be loaded by frontend");
assert.ok(js.includes('loadRobinhoodStrategyDiagnostics().catch('),
  "display must independently handle missing diagnostics");
assert.ok(html.includes("do not change live Robinhood order execution"),
  "proposed entry changes must be labeled shadow only");
const begin=js.indexOf("async function loadRobinhoodStrategyDiagnostics(){");
const end=js.indexOf("async function loadRobinhoodDecisionEvidence(){",begin);
assert.ok(begin>=0 && end>begin);
const ids=["rh-fee-summary-overview","rh-fee-count","rh-fee-shadow",
           "rh-fee-candidates","rh-fee-positions","rh-fee-exits"];
const nodes=Object.fromEntries(ids.map(x=>[x,{textContent:""}]));
const result={status:"READY",shadow_only:true,
 tracked_candidates:3,shadow_pass_count:1,candidates_with_excursion_samples:2,
 candidates:[{symbol:"BTC-USD",source:"COINBASE_WS",spread_pct:0.08,
  breakeven_move_pct:2.1,shadow_result:"SHADOW_REJECT_REWARD_AFTER_FEES",
  shadow_reason:"Prior swing high does not justify cost",
  mfe_gross_pct:1.3,mae_gross_pct:-0.8}],
 positions:[{symbol:"BTC-USD",samples:12,status:"CLOSED_AS_OF_WORKER_SCAN",
  mfe_estimated_net_pct:1.2,mae_estimated_net_pct:-2.9}],
 exits:[{symbol:"BTC-USD",net_return_pct:-2.1,holding_minutes:55,
  exit_reason:"STOP_LOSS",mfe_sampled_net_pct:0.5,mae_sampled_net_pct:-2.9}]};
const ctx={$:id=>nodes[id],request:async()=>result,Number,String};
vm.runInNewContext(js.slice(begin,end)+"\nthis.show=loadRobinhoodStrategyDiagnostics;",ctx);
(async()=>{
 await ctx.show();
 assert.match(nodes["rh-fee-summary-overview"].textContent,/3 qualified/);
 assert.match(nodes["rh-fee-shadow"].textContent,/1 shadow/);
 assert.match(nodes["rh-fee-candidates"].textContent,/SHADOW_REJECT_REWARD_AFTER_FEES/);
 assert.match(nodes["rh-fee-positions"].textContent,/MFE 1.20%/);
 assert.match(nodes["rh-fee-exits"].textContent,/STOP_LOSS/);
 assert.ok(!js.slice(begin,end).includes("innerHTML"),"untrusted evidence must use textContent");
 console.log("Robinhood fee-aware dashboard render & shadow-only disclosure passed");
})().catch(e=>{console.error(e);process.exitCode=1});
