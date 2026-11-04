"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const html=fs.readFileSync(path.join(__dirname,"../web/index.html"),"utf8");
const js=fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
for(const id of ["robinhood-export-performance","rh-export-performance"]){
  assert.ok(html.includes('id="'+id+'"'),"Missing Robinhood Excel control "+id);
}
assert.ok(js.includes('for(const id of ["robinhood-export-performance","rh-export-performance"])'),
  "Robinhood overview and evidence downloads must both be wired");
assert.ok(js.includes('"/api/robinhood/performance.xlsx"'),"Missing authenticated export endpoint");
assert.ok(js.includes('"autotrader-robinhood-performance.xlsx"'),"Missing workbook filename");
assert.ok(js.includes('await fetch(url,{credentials:"same-origin"'),
  "Existing session-protected workbook downloader must be reused");
assert.ok(html.includes("net P/L")&&html.includes("rejected orders"),
  "Download disclosure must describe performance data and diagnostics");
console.log("Robinhood Excel performance buttons and authenticated downloader wiring passed");
