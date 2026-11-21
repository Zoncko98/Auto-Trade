"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const html=fs.readFileSync(path.join(root,"web/index.html"),"utf8");
const source=fs.readFileSync(path.join(root,"web/app.js"),"utf8");
const css=fs.readFileSync(path.join(root,"web/workspace.css"),"utf8");
const expected=["Overview","Strategy &amp; AI","Risk &amp; Start",
                "Orders","Portfolio","Diagnostics"];
const views={
  live:["live","decisions","live-risk","live-orders","live"],
  robinhood:["robinhood","robinhood-decisions","robinhood-risk",
             "robinhood-orders","robinhood"],
  webull:["webull","webull-decisions","webull-risk","webull-orders","webull"],
  overview:["overview","reviews","settings","trades","overview"],
};
function chunkOf(view){
  const marker='id="view-'+view+'"';
  const at=html.indexOf(marker);
  assert.ok(at>=0,view+" workspace exists");
  const next=html.indexOf('<section class="view',at+marker.length);
  assert.ok(next>at,view+" workspace has next view boundary");
  return html.slice(at,next);
}
test("all four existing account dashboards have the same working six-section navigation",()=>{
  for(const [view,links] of Object.entries(views)){
    const chunk=chunkOf(view);
    const matched=chunk.match(/<nav class="account-unified-tabs"[^>]*>([\s\S]*?)<\/nav>/);
    assert.ok(matched,view+" has shared tab navigation in its original view");
    const buttons=[...matched[1].matchAll(/<button\b[^>]*data-view="([^"]+)"[^>]*>([^<]+)<\/button>/g)];
    assert.equal(buttons.length,6,view+" six tab buttons");
    assert.deepEqual(buttons.map(x=>x[2]),expected,view+" same label and ordering");
    assert.deepEqual(buttons.slice(0,5).map(x=>x[1]),links,view+" local routes");
    const focus=[...matched[1].matchAll(/data-focus-target="([^"]+)"/g)].map(x=>x[1]);
    assert.equal(focus.length,2,view+" local portfolio and diagnostics focus anchors");
    for(const target of focus)assert.ok(chunk.includes('id="'+target+'"'),view+" focus target exists");
    assert.ok(chunk.includes('class="stats-grid"'),view+" existing four metrics preserved");
    assert.ok(chunk.includes('rh-portfolio-performance'),view+" original portfolio section preserved");
    assert.ok(chunk.includes('class="content-grid"'),view+" original operations grid preserved");
  }
});
test("the original navigation still owns click handling and scroll targets are optional",()=>{
  assert.match(source,/document\.querySelectorAll\("\[data-view\]"\)/);
  assert.match(source,/showView\(button\.dataset\.view\)/);
  assert.match(source,/button\.dataset\.focusTarget/);
  assert.match(source,/scrollIntoView\?\./);
  assert.doesNotMatch(source,/V2_AUTO_ARM_ALL_BROKERS|auto_submit_live/);
});
test("responsive layout applies to shared navigation without replacing account views",()=>{
  assert.match(css,/\.account-unified-tabs/);
  assert.match(css,/@media \(max-width:600px\)/);
  assert.equal((html.match(/class="account-unified-tabs"/g)||[]).length,4);
  assert.doesNotMatch(html,/id="view-v2-live"/);
});
