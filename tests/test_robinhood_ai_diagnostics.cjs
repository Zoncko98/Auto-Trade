"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const html=fs.readFileSync(path.join(__dirname,"../web/index.html"),"utf8");
const js=fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
for(const id of ["rh-ai-review-diagnostics","rh-ai-outcome","rh-ai-duration",
                  "rh-ai-classifier","rh-ai-candidate-explanations"]){
  assert.ok(html.includes('id="'+id+'"'),id+" present in dashboard");
}
const begin=js.indexOf("function renderRobinhoodAIReview(data){");
const end=js.indexOf("async function loadRobinhoodDecisionEvidence(){",begin);
assert.ok(begin>=0&&end>begin);
const nodes={};
for(const id of ["rh-ai-outcome","rh-ai-duration","rh-ai-classifier",
  "rh-ai-candidate-explanations"])nodes[id]={textContent:""};
const context={$:id=>nodes[id],Number};
vm.runInNewContext(js.slice(begin,end)+"\nthis.render=renderRobinhoodAIReview;",context);
context.render({worker:{ai_review_status:"NEWS_EVIDENCE_MISSING",
  ai_review_duration_seconds:0.19,ai_candidate_reviews:[{
    symbol:"LDO-USD",outcome:"NEWS_EVIDENCE_MISSING",elapsed_seconds:0.19,
    model:null,reason:"No headlines explicitly tied to this crypto asset"}]}});
assert.equal(nodes["rh-ai-outcome"].textContent,"NEWS_EVIDENCE_MISSING");
assert.match(nodes["rh-ai-classifier"].textContent,/Model not invoked/);
assert.match(nodes["rh-ai-candidate-explanations"].textContent,/no model invoked/);
context.render({worker:{ai_review_status:"AI_NO_TRADE",
  ai_review_duration_seconds:4.82,ai_candidate_reviews:[{
    symbol:"ZEC-USD",outcome:"AI_NO_TRADE",elapsed_seconds:4.82,
    model:"local:qwen3.5:9b",classifier_model_source:"verified_text_fallback",
    reason:"AI news gate NO TRADE; sentiment=-1"}]}});
assert.equal(nodes["rh-ai-outcome"].textContent,"AI_NO_TRADE");
assert.match(nodes["rh-ai-duration"].textContent,/4\.8 seconds/);
assert.match(nodes["rh-ai-classifier"].textContent,/local:qwen3\.5:9b/);
assert.match(nodes["rh-ai-candidate-explanations"].textContent,/NO TRADE/);
assert.ok(js.includes('NEWS_EVIDENCE_MISSING:"Relevant news missing"'));
console.log("Robinhood AI evidence UI: news-missing vs model-veto, timing and classifier identity passed");
