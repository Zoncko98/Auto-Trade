# Separate AI prediction workstation (Windows)

This optional component is independent from TrueNAS and Ollama. It runs three
specialized research models on a Windows AI workstation, exposes a read-only API
and never receives Schwab credentials or account data.

Requirements: Python 3.12, recommended 16+ GB system RAM, Internet to fetch
public datasets/weights on first run. The initial Chronos-Bolt/FinBERT inference
paths run on CPU; compatible NVIDIA GPU use can be optimized later.

PowerShell (from this directory):

    python -m venv --system-site-packages .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe warm_models.py

First run downloads public weights for amazon/chronos-bolt-tiny and
ProsusAI/finbert. Review third-party model licenses before redistributing.
No weight files or external API secrets are committed to the repository.

Set environment variables to enable inbound LAN access:

    $env:AUTOTRADER_AI_BIND='192.168.1.100'
    $env:AUTOTRADER_AI_PORT='8766'
    .\start_forecast.ps1

Substitute this computer's actual private IP. Restrict the Windows Firewall
inbound TCP rule to the TrueNAS IP only. Without AUTOTRADER_AI_BIND, the service
listens on 127.0.0.1 and is not reachable from the NAS.
Configure the same URL as the optional Forecast API in the TrueNAS installer.

Read-only routes:
- GET /health — model status
- GET /api/models — installed local Ollama tags, plus model availability
- GET /api/forecast — last completed five-candidate research output

A manual refresh POST is permitted only from this computer's loopback.
The scheduler refreshes on startup, after each US weekday market close and
Monday before the opening bell (New York time). A production version should
further account for holidays and exchange early closes.

LightGBM must beat a chronological zero-return baseline to influence rankings;
otherwise the rank falls back to transparent technical rules. Forecasts are
uncalibrated and NEVER authorize live orders. Market data uses public third-party
endpoints without contractual real-time guarantees.
