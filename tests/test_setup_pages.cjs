"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const code=fs.readFileSync(path.resolve(__dirname,"../web/setup.js"),"utf8");
function page(fields,pathname){
  const inputs=Object.fromEntries(Object.entries(fields).map(([id,value])=>[
    "setup-"+id,typeof value==="boolean"?{checked:value,value:""}:{value,checked:false}
  ]));
  const context={
    location:{pathname},document:{
      getElementById(id){return inputs[id]||null},
      addEventListener(){}
    },console
  };
  vm.runInNewContext(code+"\nglobalThis.__test={values,validNewPassword};",context);
  return context.__test;
}
const first=page({provider:"ollama",ollama:"http://192.168.1.21:11434",
  model:"qwen3.5:4b"},"/setup.html");
const install=first.values();
assert.equal(install.ai_provider,"ollama");
assert.equal(install.ai_model,"qwen3.5:4b");
assert.equal(Object.hasOwn(install,"schwab_app_key"),false);
assert.equal(Object.hasOwn(install,"paper_enabled"),false);
assert.equal(Object.hasOwn(install,"market_enabled"),false);
assert.equal(Object.hasOwn(install,"forecast_url"),false);
assert.equal(first.validNewPassword("Abcdefgh1!"),true);
for(const invalid of ["Ab1!","alllowercase12!","NoNumberHere!","NoSymbol234A","NewLine0A!\n"])
  assert.equal(first.validNewPassword(invalid),false,invalid);
const ai=page({provider:"none",forecast:"", "forecast-mode":"built_in",
  "forecast-ai-review":true},"/integrations.html").values();
assert.equal(ai.forecast_mode,"built_in");
assert.equal(ai.forecast_ai_review,true);
assert.equal(Object.hasOwn(ai,"schwab_app_secret"),false);
assert.equal(Object.hasOwn(ai,"paper_enabled"),false);
const broker=page({"schwab-key":"synthetic-developer-key",
  "schwab-secret":"synthetic-fake-secret",
  "schwab-callback":"https://127.0.0.1:8182",market:true},
  "/broker-schwab.html").values();
assert.equal(broker.schwab_app_key,"synthetic-developer-key");
assert.equal(broker.market_enabled,true);
assert.equal(Object.hasOwn(broker,"ai_provider"),false);
assert.equal(Object.hasOwn(broker,"paper_enabled"),false);
console.log("PASS: first-run, AI and broker payloads are separated; new-password UI rule validated");
