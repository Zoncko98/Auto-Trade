"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const read=x=>fs.readFileSync(path.join(__dirname,"..",x),"utf8");
test("Robinhood spot buying power is labeled, not confused with stock settlement",()=>{
 const page=read("web/v2-status.js");
 assert.match(page,/Signed spot USD spending allowance/);
 assert.match(page,/not settled stock cash/);
 assert.match(page,/Signed crypto 24\/7 capability/);
});
test("Signed Robinhood spot proof never disables stock settlement safety",()=>{
 const gates=read("app/trader_v2/launch_gates.py");
 assert.match(gates,/spot_buying_power_verified/);
 assert.match(gates,/crypto_24x7_access_verified/);
 assert.match(gates,/signed_settled_cash_verified/);
 assert.match(gates,/settled_cash_verified/);
});
