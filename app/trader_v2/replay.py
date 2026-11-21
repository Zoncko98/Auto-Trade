"""Deterministic historical candle replay through the *same* V2 paper pipeline.

Illustrative synthetic spreads and fills; results are not broker-executable
quotes or evidence of profitability. No live broker imports, access or orders.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from .engine import PaperPipeline
from .models import AssetClass, Candle, MarketSnapshot, RiskPolicy, amount
from .simulation import SimulatedBroker
from .store import EventStore
from .strategies import StockController, CryptoController

def replay_candles(candles: list[Candle], asset_class: AssetClass, *,
                   policy: RiskPolicy | None = None, starting_cash="1000",
                   fee_bps="5", slippage_bps="5", spread_bps="10") -> dict:
    if asset_class not in (AssetClass.STOCK, AssetClass.CRYPTO):
        raise ValueError("Unsupported replay asset class")
    if not isinstance(candles, list) or len(candles) < 10 or len(candles) > 100000:
        raise ValueError("Replay needs 10 to 100000 ordered candles")
    if any(not isinstance(c, Candle) or not c.closed for c in candles):
        raise ValueError("Historical replay only accepts closed canonical candles")
    if len({c.symbol for c in candles}) != 1:
        raise ValueError("One symbol per replay")
    times = [c.observed_at for c in candles]
    if any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError("Replay timestamps must be increasing and unique")
    cash = amount(starting_cash, "initial simulated cash", False)
    fees = amount(fee_bps, "fee bps")
    slippage = amount(slippage_bps, "slippage bps")
    spread = amount(spread_bps, "spread bps")
    if max(fees, slippage, spread) > 1000:
        raise ValueError("Unreasonable synthetic cost")
    policy = policy or RiskPolicy()
    if not isinstance(policy, RiskPolicy):
        raise TypeError("RiskPolicy required")
    controller = StockController() if asset_class is AssetClass.STOCK else CryptoController()
    clock = [times[0]]
    account = "replay-stock" if asset_class is AssetClass.STOCK else "replay-crypto"
    outcomes = []
    with TemporaryDirectory(prefix="v2-replay-") as folder:
        base = Path(folder)
        broker = SimulatedBroker(base/"sim.sqlite3", fee_bps=fees,
                                 slippage_bps=slippage, clock=lambda: clock[0])
        broker.seed(account, asset_class, cash, fractional=asset_class is AssetClass.CRYPTO)
        store = EventStore(base/"intents.sqlite3")
        engine = PaperPipeline(broker, store)
        entry_count = exit_count = 0
        active_date = None
        for i, candle in enumerate(candles):
            clock[0] = candle.observed_at
            if active_date != clock[0].date():
                active_date = clock[0].date()
                entry_count = exit_count = 0
            half = candle.close * spread / Decimal("20000")
            quote = MarketSnapshot(candle.symbol, asset_class, "replay-synthetic",
                    clock[0], clock[0], candle.close-half, candle.close+half,
                    candle.close, True)
            broker.quote(quote)
            candidate = controller.candidate(account, candles[:i+1])
            if candidate is None:
                continue
            result = engine.evaluate(candidate, quote, policy, now=clock[0],
                                     entries_today=entry_count, exits_today=exit_count)
            outcomes.append({"at":clock[0].isoformat(), "side":candidate.side.value,
                             "result":result.code, "reason":result.reason})
            if result.code == "FILLED":
                if candidate.side.value == "BUY":
                    entry_count += 1
                else:
                    exit_count += 1
        final = broker.account(account)
        gross_buy_hold = cash * (candles[-1].close/candles[0].close - Decimal("1"))
        return {"mode":"HISTORICAL_SYNTHETIC_REPLAY_ONLY",
                "live_orders_submitted":0,"asset_class":asset_class.value,
                "symbol":candles[0].symbol,"candles":len(candles),
                "signals":len(outcomes),
                "fills":sum(x["result"]=="FILLED" for x in outcomes),
                "blocked":sum(x["result"]!="FILLED" for x in outcomes),
                "final_equity":str(final.equity),
                "net_pnl_after_simulated_costs":str(final.equity-cash),
                "gross_buy_hold_reference":str(gross_buy_hold),
                "outcomes":outcomes}
