"""Full Robinhood worker simulation of externally sold PEPE and ZEC followed by HYPE."""
import json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from robinhood_order_journal import OrderJournal
from robinhood_worker import run_once

class Broker:
    def __init__(self,now):
        self.now=now
        self.writes=[]
        self.buy_records=[]
        for symbol,qty,cost,mins in (("PEPE-USD","5194138","0.0000048",90),
                                    ("ZEC-USD","0.00527","1181.70",210)):
            self.buy_records.append({
                "id":"buy-"+symbol,"client_order_id":"bot-"+symbol,
                "symbol":symbol,"side":"buy","state":"filled",
                "filled_asset_quantity":qty,"average_price":cost,
                "fee_charged":"0.01",
                "updated_at":(now-timedelta(minutes=mins)).isoformat()})
        self.external=[
            {"id":"external-pepe","client_order_id":"external-client-pepe",
             "symbol":"PEPE-USD","side":"sell","state":"filled",
             "filled_asset_quantity":"5194138",
             "updated_at":(now-timedelta(minutes=65)).isoformat()},
            {"id":"external-zec","client_order_id":"external-client-zec",
             "symbol":"ZEC-USD","side":"sell","state":"filled",
             "filled_asset_quantity":"0.00527",
             "updated_at":(now-timedelta(minutes=60)).isoformat()}]
    def list_accounts(self):
        return [{"account_number":"acct","status":"active","is_api_tradable":True,
                 "buying_power_currency":"USD","buying_power":"53.61"}]
    def positions(self,account):return []
    def orders(self,account):return self.buy_records+self.external
    def order(self,account,order_id):
        return {"id":order_id,"state":"open"}
    def trading_pairs(self):
        return [{"symbol":symbol,"asset_code":symbol[:-4],"quote_code":"USD",
                 "is_api_tradable":True,"min_order_amount":"0.10",
                 "asset_increment":"0.001" if symbol=="HYPE-USD" else "0.00000001",
                 "max_order_size":"100000000000"}
                for symbol in ("PEPE-USD","ZEC-USD","HYPE-USD")]
    def quote(self,symbol):
        prices={"PEPE-USD":("0.00000485","0.00000487"),
                "ZEC-USD":("1189.37","1189.67"),
                "HYPE-USD":("87.017","87.031")}
        bid,ask=prices[symbol]
        return {"results":[{"symbol":symbol,"bid":bid,"ask":ask}]}
    def submit_order(self,account,intent):
        self.writes.append(dict(intent))
        return {"id":"fake-broker-ack"}

class ExternalWorkerTests(unittest.TestCase):
    def test_manual_sells_remediate_stale_inventory_before_hype_buy(self):
        now=datetime.now(timezone.utc)
        broker=Broker(now)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"robinhood";path.mkdir()
            (path/"risk_policy.json").write_text(json.dumps({
                "enabled":True,"account":"acct","max_order_usd":"7.50",
                "max_total_exposure_usd":"35","max_daily_loss_usd":"5",
                "max_open_positions":8,"verified_broker_minimum_usd":"0.1",
                "min_hold_minutes":15,"min_profit_pct":"1",
                "stop_loss_pct":"2","fee_buffer_pct":"0.25"}))
            journal=OrderJournal(root)
            for r in broker.buy_records:
                journal.record_intent("acct",r["client_order_id"],r["symbol"],
                                      r["filled_asset_quantity"],r["average_price"])
                journal.reconcile("acct",[r])
            self.assertEqual(len(journal.positions()),2)
            (path/"quote_history.json").write_text(json.dumps([
                {"symbol":"HYPE-USD","mid":m,
                 "at":(now-timedelta(seconds=sec)).isoformat()}
                for m,sec in (("86.50",430),("86.70",280),("86.85",135))]))
            with patch("robinhood_crypto_execution.RobinhoodCryptoTradingAdapter.from_state_authorized",return_value=broker),\
                 patch("local_ai_gateway.installed_models",return_value=["qwen3.5:9b"]),\
                 patch("ai_research.approve_entry",return_value=(True,"Validated approval")),\
                 patch("ai_research.research_evidence",return_value={"model":"qwen3.5:9b"}):
                result=run_once(root,broker)
            self.assertEqual(len(broker.writes),1)
            self.assertEqual(broker.writes[0]["symbol"],"HYPE-USD")
            self.assertEqual(broker.writes[0]["side"],"buy")
            self.assertEqual(result["external_holding_reconciliation"][0]["status"],
                             "EXTERNAL_SALE_RECONCILED")
            self.assertEqual({x["symbol"] for x in result["external_closed_positions"]},
                             {"PEPE-USD","ZEC-USD"})
            self.assertEqual(result["bot_open_positions"],0)
            self.assertIn(result["execution_status"],("ORDER_ACCEPTED","ORDER_SUBMITTED_UNCONFIRMED"))
            self.assertEqual(set(journal.positions()),set())
            self.assertEqual(len(journal.pending()),1)
if __name__=="__main__":unittest.main()
