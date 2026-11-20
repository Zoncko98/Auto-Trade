"""Auto Trader V2 feature-gated shared core. Paper/replay only; never imports live broker clients."""
from .models import *
from .store import EventStore
from .simulation import SimulatedBroker
from .strategies import StockController,CryptoController
from .risk import evaluate_risk
from .engine import PaperPipeline
from .readonly_adapters import ReadOnlyBrokerRegistry, AccountObservation
from .cached_provider import CachedMarketDataProvider
from .market_sources import MarketSourceError, QuoteReading
