"""Deterministic persistent simulated brokerage for V2 paper/replay only.

No network access, broker credentials, OAuth, or live submission facilities.
Broker acknowledgments are stored independently of the V2 intent journal so
crash-after-fill-before-ack can be reconciled by the ORIGINAL idempotency key.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
from contextlib import contextmanager
import json,os,sqlite3
from .contracts import BrokerExecution
from .models import Account,AssetClass,AuthState,Capability,MarketSnapshot,OrderIntent,OrderSide,amount

_CENT=Decimal("0.01")
class SimulationRejected(ValueError):pass

class SimulatedBroker:
    provider_id="simulation"
    def __init__(self,path,*,fee_bps=Decimal("0"),slippage_bps=Decimal("0")):
        self.path=Path(path)
        self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.path.parent.stat().st_mode & 0o007:
            raise PermissionError("Simulation directory is world-accessible")
        if not self.path.exists():
            try:
                fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            except FileExistsError:pass
        if self.path.stat().st_mode & 0o077:raise PermissionError("Unsafe simulation ledger permissions")
        self.fee_bps=amount(fee_bps,"fee bps")
        self.slippage_bps=amount(slippage_bps,"slippage bps")
        if self.fee_bps>1000 or self.slippage_bps>1000:raise ValueError("Unsupported simulation costs")
        self._quotes={}
        with self._connect() as db:
            mode=db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode.lower()!="wal":raise RuntimeError("Simulation WAL unavailable")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sim_accounts(
                  account_id TEXT PRIMARY KEY,asset_class TEXT NOT NULL,cash TEXT NOT NULL,
                  fractional INTEGER NOT NULL,enabled INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sim_positions(
                  account_id TEXT NOT NULL,symbol TEXT NOT NULL,qty TEXT NOT NULL,
                  average_cost TEXT NOT NULL,mark TEXT NOT NULL,
                  PRIMARY KEY(account_id,symbol));
                CREATE TABLE IF NOT EXISTS sim_orders(
                  key TEXT PRIMARY KEY,account_id TEXT NOT NULL,
                  intent_document TEXT NOT NULL,broker_order_id TEXT NOT NULL,
                  quantity TEXT NOT NULL,price TEXT NOT NULL,fee TEXT NOT NULL,
                  created_at TEXT NOT NULL);
            """)

    def _connect(self):
        db=sqlite3.connect(str(self.path),isolation_level=None,timeout=10)
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def _tx(self):
        db=self._connect()
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:db.execute("ROLLBACK")
            raise
        finally:db.close()

    def seed(self,account_id,asset_class:AssetClass,initial_cash,*,fractional=False):
        """Only initializes a NEW virtual account. Never resets existing balances."""
        from .models import valid_id
        valid_id(account_id)
        if not isinstance(asset_class,AssetClass):raise ValueError("Invalid simulated asset class")
        cash=amount(initial_cash,"virtual cash",False)
        with self._tx() as db:
            existing=db.execute("SELECT account_id FROM sim_accounts WHERE account_id=?",(account_id,)).fetchone()
            if existing:return False
            db.execute("INSERT INTO sim_accounts VALUES(?,?,?,?,?)",
                       (account_id,asset_class.value,str(cash),int(fractional),1))
        return True

    def quote(self,snapshot:MarketSnapshot):
        if not isinstance(snapshot,MarketSnapshot):raise ValueError("Validated market snapshot required")
        self._quotes[(snapshot.symbol,snapshot.asset_class)]=snapshot

    def account(self,account_id):
        with self._connect() as db:
            row=db.execute("SELECT * FROM sim_accounts WHERE account_id=?",(account_id,)).fetchone()
            if row is None:raise KeyError("Unknown simulated account")
            positions=db.execute("SELECT * FROM sim_positions WHERE account_id=?",(account_id,)).fetchall()
        asset=AssetClass(row["asset_class"])
        total=Decimal("0")
        quantities={}
        for position in positions:
            qty=Decimal(position["qty"])
            market=self._quotes.get((position["symbol"],asset))
            mark=market.last if market else Decimal(position["mark"])
            quantities[position["symbol"]]=qty
            total+=qty*mark
        cash=Decimal(row["cash"])
        return Account(account_id,self.provider_id,Capability(frozenset({asset}),
            fractional=bool(row["fractional"]),min_notional=Decimal("1")),
            cash=cash,equity=cash+total,positions=quantities,
            auth=AuthState.CONNECTED,trading_enabled=bool(row["enabled"]),market_exposure=total)

    def _parse_order(self,row):
        return BrokerExecution(key=row["key"],state="FILLED",
              broker_order_id=row["broker_order_id"],filled_quantity=Decimal(row["quantity"]),
              average_price=Decimal(row["price"]),fees=Decimal(row["fee"]))

    def find_order(self,key):
        with self._connect() as db:
            row=db.execute("SELECT * FROM sim_orders WHERE key=?",(key,)).fetchone()
            return self._parse_order(row) if row else None

    @staticmethod
    def _document(intent):
        return json.dumps({"account_id":intent.account_id,"symbol":intent.symbol,
                "asset_class":intent.asset_class.value,"side":intent.side.value,
                "quantity":str(intent.quantity),"limit_price":str(intent.limit_price)},
                sort_keys=True,separators=(",",":"))

    def submit(self,intent:OrderIntent)->BrokerExecution:
        if not isinstance(intent,OrderIntent):raise ValueError("Canonical order intent required")
        market=self._quotes.get((intent.symbol,intent.asset_class))
        if market is None:raise SimulationRejected("No verified quote")
        if not market.market_open:raise SimulationRejected("Session closed")
        if (datetime.now(timezone.utc)-market.observed_at).total_seconds()>120:
            raise SimulationRejected("Stale quote")
        doc=self._document(intent)
        with self._tx() as db:
            existing=db.execute("SELECT * FROM sim_orders WHERE key=?",(intent.key,)).fetchone()
            if existing:
                if existing["intent_document"]!=doc:
                    raise SimulationRejected("Idempotency collision")
                return self._parse_order(existing)
            account=db.execute("SELECT * FROM sim_accounts WHERE account_id=?",
                               (intent.account_id,)).fetchone()
            if account is None or not account["enabled"] or account["asset_class"]!=intent.asset_class.value:
                raise SimulationRejected("Account disabled or asset unsupported")
            if intent.quantity!=intent.quantity.to_integral_value() and not account["fractional"]:
                raise SimulationRejected("Account requires whole shares")
            slip=self.slippage_bps/Decimal("10000")
            reference=market.ask if intent.side is OrderSide.BUY else market.bid
            fill_price=(reference*(1+slip if intent.side is OrderSide.BUY else 1-slip))
            fill_price=fill_price.quantize(Decimal("0.00000001"),rounding=ROUND_HALF_UP)
            if (intent.side is OrderSide.BUY and fill_price>intent.limit_price) or (
                 intent.side is OrderSide.SELL and fill_price<intent.limit_price):
                raise SimulationRejected("Limit is not executable")
            notional=intent.quantity*fill_price
            if notional<1:raise SimulationRejected("Below simulated minimum order")
            fee=(notional*self.fee_bps/Decimal("10000")).quantize(_CENT,rounding=ROUND_HALF_UP)
            cash=Decimal(account["cash"])
            row=db.execute("SELECT * FROM sim_positions WHERE account_id=? AND symbol=?",
                          (intent.account_id,intent.symbol)).fetchone()
            held=Decimal(row["qty"]) if row else Decimal("0")
            if intent.side is OrderSide.BUY and cash < notional+fee:
                raise SimulationRejected("Insufficient simulated cash after fees")
            if intent.side is OrderSide.SELL and held < intent.quantity:
                raise SimulationRejected("Insufficient simulated holdings")
            new_cash=cash-notional-fee if intent.side is OrderSide.BUY else cash+notional-fee
            if new_cash<0:raise SimulationRejected("Negative simulated cash")
            if intent.side is OrderSide.BUY:
                new_qty=held+intent.quantity
                old_basis=Decimal(row["average_cost"]) if row else Decimal("0")
                basis=(held*old_basis+notional+fee)/new_qty
                db.execute("""INSERT INTO sim_positions VALUES(?,?,?,?,?)
                    ON CONFLICT(account_id,symbol) DO UPDATE
                    SET qty=excluded.qty,average_cost=excluded.average_cost,mark=excluded.mark""",
                    (intent.account_id,intent.symbol,str(new_qty),str(basis),str(market.last)))
            elif held==intent.quantity:
                db.execute("DELETE FROM sim_positions WHERE account_id=? AND symbol=?",
                           (intent.account_id,intent.symbol))
            else:
                db.execute("UPDATE sim_positions SET qty=?,mark=? WHERE account_id=? AND symbol=?",
                           (str(held-intent.quantity),str(market.last),intent.account_id,intent.symbol))
            db.execute("UPDATE sim_accounts SET cash=? WHERE account_id=?",
                       (str(new_cash),intent.account_id))
            db.execute("INSERT INTO sim_orders VALUES(?,?,?,?,?,?,?,?)",
                       (intent.key,intent.account_id,doc,"SIM-"+intent.key,
                        str(intent.quantity),str(fill_price),str(fee),
                        datetime.now(timezone.utc).isoformat()))
            return BrokerExecution(intent.key,"FILLED","SIM-"+intent.key,
                                   intent.quantity,fill_price,fee)
