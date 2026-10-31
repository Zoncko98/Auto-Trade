# Forecast research: three options, one TrueNAS app

New in v1.0.9: You do not need to install LightGBM, Chronos-Bolt or FinBERT anywhere. The standard Auto Trader image now has a NAS-native forecast mode that uses genuine dated historical prices/volume. It requires no extra workstation, separate container, broker login or AI weight installation.

The first-run wizard and Profile / Integrations offer:

| Mode | Requirements | Function |
| --- | --- | --- |
| Automatic (recommended) | None | Use a healthy specialist companion if configured; otherwise built-in NAS analysis |
| Built-in NAS | None | Historical daily prices, price/volume screens, trend, momentum, volatility, heuristic ranking and risk levels |
| Advanced | Optional separate AI computer | Chronos-Bolt/FinBERT/LightGBM research and calibration; the NAS-native fallback remains |

## Optional existing provider commentary

The checkbox Add public-news review using my selected AI provider sends only public, dated financial-news headlines to the user's already configured Ollama or ChatGPT/Gemini OAuth companion for a qualitative assessment of catalysts, sentiment and downside risks.

No account numbers, positions, tokens, brokerage orders or passwords are transmitted. The model cannot change computed prices, filters, ranking, volatility bands or execution permission. Unsupported/malformed provider responses are omitted.

Cloud-only caveat: current ChatGPT and Gemini OAuth still use the optional authenticated companion hosted on a private-LAN computer; the checkbox is not native cloud account login inside the NAS. Users without a companion can use complete NAS-native technical research with optional commentary off. Direct supported cloud sign-in on NAS requires additional implementation and verification.

## Built-in research details

- Fixed universe of 24 symbols: F, T, PFE, AAL, CCL, SOFI, SNAP, NU, WBD, NIO, NOK, VALE, UAA, PLUG, RIG, LUMN, KGC, AG, CLF, BTG, BBD, HIMS, GOLD, ACHR. This is not a whole-market scan.
- Daily history: public Yahoo Finance historical chart with Stooq CSV fallback. Data-feed availability and usage terms can change. Missing, outdated or malformed data is marked unavailable, not invented.
- Eligibility: at least 100 valid daily bars, latest close $5 to $25, 20-day average volume at least 200,000 shares and last daily close at most six calendar days old.
- Features: five-/20-session return, 5/20/50-session trend comparisons, 20-session realized log-return volatility, relative volume, 10-session recent high/low.
- Ranking: bounded reproducible historical-data heuristic. A score is NOT a calibrated price, win probability or trade recommendation.
- Descriptive band: last close plus/minus one observed historical daily volatility standard deviation. Not a future price confidence interval.
- Output: at most five dated research candidates, observed source, risk invalidation levels, unmet technical checks and optional user-selected AI news review.
- Caching: asynchronous research generation, saved under private persistent /state, re-evaluated periodically. First use can show Preparing built-in research until current historical data loads.
- Broker quotes: separately connect read-only Schwab quote monitor for a current bid/ask context. Quotes do not replace dated historical training data or authorize orders.

The forecast page and the first-run wizard explain the calculations. Refresh display checks the latest dated research snapshot, and never submits live trades.

## Optional specialized forecasting on another computer

To use the original Chronos-Bolt, LightGBM and FinBERT models, see ai-workstation/README.md and ai-workstation/start_forecast.ps1, which run a read-only API on port 8766. Optional advanced inference remains outside the TrueNAS image. When this service is unavailable, the NAS-native research fallback continues.

Security: keep NAS market feeds and AI providers behind private networking, do not share Schwab credentials, and understand that heuristic rankings and AI commentary are experimental research rather than promises of profit.
