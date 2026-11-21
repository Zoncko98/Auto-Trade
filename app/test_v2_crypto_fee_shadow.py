"""Cost-aware V2 crypto shadow is deterministic, conservative and non-authorizing."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
from pathlib import Path
from trader_v2.models import AssetClass,Candle,Candidate,MarketSnapshot,OrderSide
from trader_v2.crypto_fee_shadow import assess
from trader_v2.fresh_paper import run_once
import sqlite3

class FeeShadowTests(TestCase):
    def setUp(self):
        self.now=datetime(2026,11,21,16,0,10,tzinfo=timezone.utc)
        self.signal_at=self.now.replace(second=0)
        self.symbol="BTCUSD"
        self.times=[self.signal_at-timedelta(minutes=i) for i in range(20,-1,-1)]
        self.bars=[Candle(self.symbol,t,Decimal("100")) for t in self.times]
        self.candidate=Candidate("crypto_sma","baseline-1","v2-paper-btcusd",
             self.symbol,AssetClass.CRYPTO,OrderSide.BUY,self.signal_at,
             {"indicator":"SMA_CROSS"})
        self.quote=self.market()

    def market(self,bid="99.95",ask="100.05",last="100",observed=None):
        return MarketSnapshot(self.symbol,AssetClass.CRYPTO,
            "coinbase_public_paper",observed or (self.now-timedelta(seconds=2)),
            self.now,Decimal(bid),Decimal(ask),Decimal(last),True)

    def test_past_resistance_with_fee_adjusted_room_passes_only_as_counterfactual(self):
        bars=list(self.bars)
        bars[8]=Candle(self.symbol,bars[8].observed_at,Decimal("103"))
        report=assess(self.candidate,self.quote,bars,now=self.now)
        self.assertEqual(report["state"],"SHADOW_PASS_PAST_RESISTANCE_ROOM")
        self.assertGreater(Decimal(report["hypothetical_net_at_prior_high_pct"]),Decimal("0.5"))
        self.assertEqual(report["historical_resistance_close"],"103")
        self.assertEqual(report["reference_candles"],20)
        self.assertFalse(report["changed_execution"])
        self.assertFalse(report["live_order_authorized"])
        self.assertFalse(report["market_target_is_forecast"])

    def test_tight_prior_resistance_loses_to_bid_ask_fees_and_slippage(self):
        report=assess(self.candidate,self.quote,self.bars,now=self.now)
        self.assertEqual(report["state"],"SHADOW_REJECT_REWARD_AFTER_FEES")
        self.assertLess(Decimal(report["hypothetical_net_at_prior_high_pct"]),0)
        self.assertEqual(report["model_fee_bps_per_side"],"5")
        self.assertEqual(report["model_slippage_bps_per_side"],"5")
        self.assertEqual(report["minimum_hypothetical_net_pct"],"0.500")

    def test_large_spread_rejects_without_guessing_reward(self):
        report=assess(self.candidate,self.market(bid="99",ask="100"),self.bars,now=self.now)
        self.assertEqual(report["state"],"SHADOW_REJECT_SPREAD")
        self.assertNotIn("hypothetical_net_at_prior_high_pct",report)

    def test_missing_trailing_evidence_does_not_assume_profit(self):
        report=assess(self.candidate,self.quote,self.bars[-9:],now=self.now)
        self.assertEqual(report["state"],"INSUFFICIENT_HISTORY")
        self.assertFalse(report["changed_execution"])

    def test_history_is_contiguous_and_uses_only_prior_close(self):
        bars=list(self.bars)
        bars[-1]=Candle(self.symbol,bars[-1].observed_at,Decimal("150"))
        report=assess(self.candidate,self.quote,bars,now=self.now)
        self.assertEqual(report["historical_resistance_close"],"100")
        # A gap is not eligible for favorable extrapolation.
        bars[4]=Candle(self.symbol,bars[4].observed_at+timedelta(seconds=15),Decimal("1000"))
        self.assertEqual(assess(self.candidate,self.quote,bars,now=self.now)["state"],
                         "EVIDENCE_UNAVAILABLE")

    def test_stale_quote_and_mismatched_symbol_never_claimed_viable(self):
        old=self.market(observed=self.now-timedelta(minutes=5))
        self.assertEqual(assess(self.candidate,old,self.bars,now=self.now)["state"],
                         "EVIDENCE_UNAVAILABLE")
        wrong=MarketSnapshot("ETHUSD",AssetClass.CRYPTO,"coinbase_public_paper",
            self.now,self.now,Decimal("100"),Decimal("101"),Decimal("100.5"),True)
        self.assertEqual(assess(self.candidate,wrong,self.bars,now=self.now)["state"],
                         "EVIDENCE_UNAVAILABLE")

    def test_malformed_fee_and_slippage_fail_closed(self):
        for invalid in ("NaN","-1",True,"999"):
            with self.subTest(invalid=invalid):
                report=assess(self.candidate,self.quote,self.bars,now=self.now,
                              fee_bps=invalid)
                self.assertEqual(report["state"],"EVIDENCE_UNAVAILABLE")

    def test_sell_signal_never_subject_to_entry_filter(self):
        sell=Candidate("crypto_sma","baseline-1","v2-paper-btcusd",
            self.symbol,AssetClass.CRYPTO,OrderSide.SELL,self.signal_at,
            {"indicator":"SMA_CROSS"})
        report=assess(sell,self.quote,[],now=self.now)
        self.assertEqual(report["state"],"EXIT_NOT_GATED")
        self.assertFalse(report["changed_execution"])

    def test_fee_shadow_cannot_change_existing_paper_fill_sequence(self):
        prices=[10,10,10,10,10,10,10,10,10,11,12,13,12,11,10,9,8,9,10,11,12,13,12,11]
        start=datetime(2026,11,20,12,0,tzinfo=timezone.utc)
        def run_case(shadow_override=False):
            with TemporaryDirectory() as tmp:
                reports=[]
                for i,price in enumerate(prices):
                    at=start+timedelta(minutes=i,seconds=10)
                    p=Decimal(str(price))
                    quote=MarketSnapshot("BTCUSD",AssetClass.CRYPTO,
                         "coinbase_public_paper",at-timedelta(seconds=2),at,
                         p*Decimal("0.9995"),p*Decimal("1.0005"),p,True)
                    callback=lambda *args,**kwargs: {"state":"NOT_INVOKED","changed_order_authority":False}
                    with patch("trader_v2.crypto_fee_shadow.assess",
                              return_value={"state":"SHADOW_REJECT_REWARD_AFTER_FEES",
                                            "changed_execution":False,"live_order_authorized":False}
                              ) if shadow_override else patch(
                              "trader_v2.crypto_fee_shadow.assess",
                              wraps=assess):
                        report=run_once(tmp,"BTCUSD",now=at,
                          fetch=lambda symbol,now,quote=quote:quote,shadow=callback)
                    reports.append(report)
                with sqlite3.connect(str(Path(tmp)/"v2"/"fresh_paper"/"sim.sqlite3")) as db:
                    count=db.execute("SELECT COUNT(*) FROM sim_orders").fetchone()[0]
                return ([(r["scan_state"],r.get("signal")) for r in reports],count,
                        [r.get("fee_shadow",{}).get("state") for r in reports])
        base=run_case()
        veto=run_case(shadow_override=True)
        self.assertEqual(base[:2],veto[:2])
        self.assertGreater(base[1],0)
        self.assertIn("SHADOW_REJECT_REWARD_AFTER_FEES",veto[2])
        self.assertNotEqual(base[2],veto[2])

if __name__=="__main__":main()
