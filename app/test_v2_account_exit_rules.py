"""V1 exit math against signed V2 market/managed-lot contracts."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from unittest import TestCase
from trader_v2.account_exit_rules import (
    ManagedExitLot,ExitPolicy,ExitParityUnavailable,exit_trigger
)
from trader_v2.models import MarketSnapshot,AssetClass

NOW=datetime(2026,11,23,15,0,tzinfo=timezone.utc)

def snapshot(broker,bid,*,seconds=2,spread=D("0.001"),source=None):
    src=source or {"schwab":"schwab_signed",
       "webull":"webull_signed","robinhood_crypto":"robinhood_signed"}[broker]
    klass=AssetClass.CRYPTO if broker=="robinhood_crypto" else AssetClass.STOCK
    b=D(str(bid))
    return MarketSnapshot("BTC-USD" if klass is AssetClass.CRYPTO else "AAPL",
        klass,src,NOW-timedelta(seconds=seconds),NOW,b,
        b*(1+spread),b,True)

def lot(broker,cost,*,held=30,peak=None,signed_qty=D("1"),buy_today=False):
    sym="BTC-USD" if broker=="robinhood_crypto" else "AAPL"
    return ManagedExitLot(sym,D("1"),signed_qty,D(str(cost)),
        NOW-timedelta(minutes=held),
        D(str(peak)) if peak is not None else None,
        cost_basis_broker_verified=True,original_fills_reconciled=True,
        same_day_filled_buy=buy_today)

class ExitParityTests(TestCase):
    def decide(self,broker,bid,cost,*,held=30,peak=None,tech=False,policy=None):
        return exit_trigger(broker,lot(broker,cost,held=held,peak=peak),
            snapshot(broker,bid),policy or ExitPolicy(broker),
            now=NOW,technical_reversal=tech)
    def test_webull_v1_stop_loss_uses_025_fee(self):
        self.assertEqual(self.decide("webull",D("97.5"),D("100")),"STOP_LOSS")
        self.assertEqual(self.decide("webull",D("99"),D("100"),held=2),"HOLD")
    def test_webull_v1_take_profit_requires_15_min(self):
        self.assertEqual(self.decide("webull",D("104"),D("100"),held=20),"TAKE_PROFIT")
        self.assertEqual(self.decide("webull",D("104"),D("100"),held=14),"HOLD")
    def test_webull_v1_trailing_retreat_requires_remaining_profit(self):
        self.assertEqual(self.decide("webull",D("102"),D("100"),
                    peak=D("104"),held=20),"TRAILING_PROFIT")
        self.assertEqual(self.decide("webull",D("100"),D("100"),
                    peak=D("104"),held=20),"HOLD")
    def test_webull_technical_reversal_requires_profit(self):
        self.assertEqual(self.decide("webull",D("102"),D("100"),tech=True),"PROFIT_REVERSAL")
        self.assertEqual(self.decide("webull",D("100"),D("100"),tech=True),"HOLD")
    def test_robinhood_stop_keeps_original_fee_reference(self):
        p=ExitPolicy("robinhood_crypto",sell_fee_pct=D("1.3"),
                     stop_reference_fee_pct=D("0.25"))
        self.assertEqual(self.decide("robinhood_crypto",D("98.1"),D("100"),
                              policy=p),"STOP_LOSS")
        self.assertEqual(self.decide("robinhood_crypto",D("98.5"),D("100"),
                              policy=p),"HOLD")
    def test_robinhood_technical_profit_requires_min_profit(self):
        self.assertEqual(self.decide("robinhood_crypto",D("102"),D("100"),tech=True),
                         "PROFIT_REVERSAL")
        self.assertEqual(self.decide("robinhood_crypto",D("100"),D("100"),tech=True),
                         "HOLD")
    def test_schwab_exit_is_verified_bearish_cross_only(self):
        self.assertEqual(self.decide("schwab",D("10"),D("12"),tech=True),
                         "V1_SCHWAB_BEARISH_CROSS")
        self.assertEqual(self.decide("schwab",D("9"),D("12"),tech=False),"HOLD")
        self.assertEqual(exit_trigger("schwab",lot("schwab",D("12"),buy_today=True),
             snapshot("schwab",D("10")),ExitPolicy("schwab"),now=NOW,
             technical_reversal=True),"HOLD")
    def test_no_signed_cost_basis_or_reconciled_receipt(self):
        evidence=lot("webull",D("100"))
        kwargs=dict(symbol="AAPL",quantity=D("1"),signed_available_quantity=D("1"),
            cost_basis=D("100"),opened_at=NOW-timedelta(minutes=20))
        for flags in ({"cost_basis_broker_verified":False,
                       "original_fills_reconciled":True},
                      {"cost_basis_broker_verified":True,
                       "original_fills_reconciled":False}):
            with self.assertRaises(ExitParityUnavailable):
                exit_trigger("webull",ManagedExitLot(**kwargs,**flags),
                    snapshot("webull",D("90")),ExitPolicy("webull"),now=NOW)
    def test_bot_lots_cannot_exceed_signed_available(self):
        with self.assertRaises(ExitParityUnavailable):
            lot("robinhood_crypto",D("100"),signed_qty=D("0.5"))
    def test_untrusted_or_stale_quote_cannot_generate_exit(self):
        with self.assertRaises(ExitParityUnavailable):
            exit_trigger("webull",lot("webull",D("100")),
                snapshot("webull",D("90"),source="coinbase_public_paper"),
                ExitPolicy("webull"),now=NOW)
        with self.assertRaises(ExitParityUnavailable):
            exit_trigger("webull",lot("webull",D("100")),
                snapshot("webull",D("90"),seconds=75),
                ExitPolicy("webull"),now=NOW)
    def test_webull_policy_drift_fails_closed(self):
        with self.assertRaises(ExitParityUnavailable):
            ExitPolicy("webull",stop_loss_pct=D("3"))
    def test_external_quote_or_symbol_cannot_authorize_sell(self):
        with self.assertRaises(ExitParityUnavailable):
            exit_trigger("webull",lot("webull",D("100")),
                snapshot("robinhood_crypto",D("90")),
                ExitPolicy("webull"),now=NOW)
