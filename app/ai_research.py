"""AI-supported trade research for Auto Trader.

Only current public news is sent to the configured local model. Never sends brokerage
positions, account numbers, or API credentials to the model. AI outputs are
qualitative and MUST NOT be represented as calibrated probabilities.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import os
import re
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from openwebui_gateway import classify_news, GatewayUnavailable

COMPANIES = {
    'F':'Ford Motor Company', 'T':'AT&T', 'PFE':'Pfizer',
    'AAL':'American Airlines Group', 'CCL':'Carnival Corporation',
    'SOFI':'SoFi Technologies', 'SNAP':'Snap Inc', 'NU':'Nu Holdings',
    'WBD':'Warner Bros Discovery', 'NIO':'NIO Inc', 'NOK':'Nokia',
    'VALE':'Vale SA', 'UAA':'Under Armour', 'PLUG':'Plug Power',
    'RIG':'Transocean', 'LUMN':'Lumen Technologies',
    'KGC':'Kinross Gold', 'AG':'First Majestic Silver',
    'CLF':'Cleveland Cliffs', 'BTG':'B2Gold', 'BBD':'Banco Bradesco',
    'HIMS':'Hims & Hers Health', 'GOLD':'Barrick Mining',
    'ACHR':'Archer Aviation',
    'BTC-USD':'Bitcoin cryptocurrency', 'ETH-USD':'Ethereum cryptocurrency',
    'SOL-USD':'Solana cryptocurrency', 'DOGE-USD':'Dogecoin cryptocurrency',
}
MAX_HEADLINES = 6
MAX_BYTES = 131072
NEWS_WINDOW = timedelta(hours=36)
# Process-local cache prevents repeated paid model requests on every scan.
_MODEL_CACHE = {}
_EVIDENCE_CACHE = {}
CACHE_WINDOW = timedelta(minutes=15)

def _model_identity():
    provider=os.getenv("AI_PROVIDER","cloud").lower()
    if provider in ("local","ollama"):
        try:
            from local_ai_gateway import _settings
            return (provider,_settings()[1],os.getenv("LOCAL_AI_NEWS_MODEL",""))
        except Exception:
            return (provider,"unavailable","")
    return (provider,os.getenv("AI_API_MODEL",""),"")


class ResearchUnavailable(Exception):
    """The evidence or AI service cannot support an entry decision."""

def fetch_headlines(symbol: str, now: datetime, fetch=None) -> list[dict]:
    """Search public RSS; require a real publisher and timestamped headlines."""
    from robinhood_crypto_gateway import PAIR
    if (symbol not in COMPANIES and not (isinstance(symbol,str) and PAIR.fullmatch(symbol))) or now.tzinfo is None:
        raise ResearchUnavailable('Unsupported symbol or naive timestamp')
    now = now.astimezone(timezone.utc)
    url = ('https://news.google.com/rss/search?q='
           + quote_plus((COMPANIES.get(symbol,symbol.removesuffix("-USD")+" cryptocurrency")+
                       (' when:2d' if symbol.endswith('-USD') else ' stock when:2d')))
           + '&hl=en-US&gl=US&ceid=US%3Aen')
    try:
        if fetch is not None:
            raw = fetch(url)
        else:
            req = Request(url, headers={'User-Agent': 'AutoTraderResearch/1.0'})
            with urlopen(req, timeout=8) as response:
                raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ResearchUnavailable('News feed exceeds size limit')
        root = ET.fromstring(raw)
    except (OSError, ValueError, ET.ParseError) as exc:
        raise ResearchUnavailable('Recent news unavailable') from None
    items, seen = [], set()
    for item in root.findall('./channel/item'):
        title = unescape((item.findtext('title') or '').strip())[:220]
        publisher = unescape((item.findtext('source') or '').strip())[:90]
        if not title or not publisher or title.casefold() in seen:
            continue
        try:
            date = parsedate_to_datetime(item.findtext('pubDate'))
            if date.tzinfo is None:
                continue
            date = date.astimezone(timezone.utc)
        except (TypeError, ValueError, AttributeError):
            continue
        if not (now - NEWS_WINDOW <= date <= now + timedelta(minutes=2)):
            continue
        seen.add(title.casefold())
        news_url=(item.findtext('link') or '').strip()
        if not news_url.startswith('https://news.google.com/'):
            news_url=''
        items.append({'title': title, 'source': publisher,
                      'published_at': date.isoformat(), 'url': news_url[:400]})
    items.sort(key=lambda item: item['published_at'], reverse=True)
    if not items:
        raise ResearchUnavailable('No independently timestamped news')
    return items[:MAX_HEADLINES]

CRYPTO_ASSET_ALIASES = {
    "BTC": ("bitcoin",), "ETH": ("ethereum",), "SOL": ("solana",),
    "DOGE": ("dogecoin",), "BCH": ("bitcoin cash",),
}
CRYPTO_CONTEXT = re.compile(
    r"\b(?:crypto(?:currency)?|token|blockchain|coin|on-chain|defi|"
    r"decentralized|digital asset|exchange listing)\b", re.I)

def crypto_headline_relevant(symbol: str, headline: dict) -> bool:
    """Do not treat unrelated stock/hardware articles as token catalysts."""
    if not symbol.endswith("-USD"):
        return True
    base = symbol[:-4]
    if not isinstance(headline, dict) or not isinstance(headline.get("title"), str):
        return False
    title = headline["title"]
    aliases = CRYPTO_ASSET_ALIASES.get(base, ())
    if any(re.search(r"(?<![a-zA-Z])"+re.escape(alias)+r"(?![a-zA-Z])", title, re.I)
           for alias in aliases):
        return True
    # Ambiguous symbols like CHIP and MON need BOTH an exact asset ticker
    # and independently indicated crypto context.
    return (bool(re.search(r"(?<![a-zA-Z])"+re.escape(base)+r"(?![a-zA-Z])", title))
            and bool(CRYPTO_CONTEXT.search(title)))

def approve_entry(symbol: str, now: datetime,
                  get_headlines=fetch_headlines,
                  classifier=classify_news) -> tuple[bool, str]:
    """Qualitative veto on a potential BUY; never submits an order.

    Technical and liquidity signals must have selected a candidate already.
    Any missing or invalid news evidence fails closed.
    """
    key = (symbol,_model_identity())
    if get_headlines is fetch_headlines and classifier is classify_news:
        cached = _MODEL_CACHE.get(key)
        if cached is not None:
            cached_at, cached_result = cached
            if now.tzinfo and cached_at <= now <= cached_at + CACHE_WINDOW:
                return cached_result
    try:
        news = get_headlines(symbol, now)
        if symbol.endswith("-USD"):
            news = [row for row in news if crypto_headline_relevant(symbol, row)]
            if not news:
                raise ResearchUnavailable("No headlines explicitly tied to this crypto asset")
        result = classifier(symbol, news)
        if not isinstance(result, dict) or result.get('ticker') != symbol:
            raise ResearchUnavailable('Wrong or missing model security')
        sentiment = result.get('sentiment')
        impact = result.get('impact')
        if type(sentiment) is not int or sentiment not in (-2, -1, 0, 1, 2):
            raise ResearchUnavailable('Sentiment not in supported range')
        if type(impact) is not int or impact not in (0, 1, 2):
            raise ResearchUnavailable('Impact not in supported range')
        catalyst, risk = result.get('catalyst'), result.get('downside_risk')
        if not all(isinstance(s, str) and 0 < len(s) < 300
                   for s in (catalyst, risk)):
            raise ResearchUnavailable('Missing bounded explanations')
        if len(news) < 1:
            raise ResearchUnavailable('No valid dated evidence')
    except (ResearchUnavailable, GatewayUnavailable) as exc:
        _EVIDENCE_CACHE.pop(symbol,None)
        return False, 'AI research unavailable: ' + str(exc)
    approved = sentiment >= 1 and impact >= 1
    evidence = (f'AI news gate {"PASS" if approved else "NO TRADE"}; '
                f'sentiment={sentiment}, impact={impact}, dated_news={len(news)}; '
                f'catalyst={catalyst}; risk={risk}; '
                'AI score is NOT a calibrated win probability')
    answer = (approved, evidence)
    _EVIDENCE_CACHE[symbol] = (now, {
        'model':str(result.get('model','local model'))[:96],
        'cache_identity':_model_identity(),
        'classifier_model_source':str(result.get('classifier_model_source','selected'))[:48],
        'inference_seconds':result.get('inference_seconds'),
        'headlines':news,'sentiment':sentiment,'impact':impact,
        'catalyst':catalyst,'downside_risk':risk,'approved':approved})
    if get_headlines is fetch_headlines and classifier is classify_news:
        _MODEL_CACHE[key] = (now, answer)
        if len(_MODEL_CACHE) > 40:
            _MODEL_CACHE.clear()
    return answer


def research_evidence(symbol, now):
    """Last validated model assessment and public inputs, never internal thoughts."""
    row=_EVIDENCE_CACHE.get(symbol)
    if row is None:return {}
    when,data=row
    if now.tzinfo and when<=now<=when+CACHE_WINDOW and data.get("cache_identity")==_model_identity():
        out=dict(data)
        out.pop("cache_identity",None)
        return out
    return {}
