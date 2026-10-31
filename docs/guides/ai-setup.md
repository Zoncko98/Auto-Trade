# Configuring Ollama, external AI APIs and forecast models

**[Documentation](../README.md) | [Architecture](../architecture.md) | [Schwab](schwab.md) | [Troubleshooting](troubleshooting.md)**

Auto Trader separates **model inference** from the **home server dashboard/trading worker**. A GPU-equipped computer may host Ollama and the independent Chronos-Bolt/LightGBM/FinBERT service.

## A. Ollama on another LAN computer

1. Install [Ollama](https://ollama.com/) on the AI computer.
2. Pull any desired compatible chat model, e.g. `ollama pull qwen3.5:4b`. Use `ollama list` to verify installed tags.
3. Configure the Ollama service to listen on its private LAN interface. For example, Ollama supports an `OLLAMA_HOST` binding; use your OS-specific service configuration. Restrict the port to your NAS at the host firewall—**do not expose port 11434 to the internet**.
4. From the **server that runs Auto Trader**, verify `http://AI-LAN-IP:11434/api/tags` returns model information:
   ```sh
   curl --fail --max-time 8 http://192.168.1.100:11434/api/tags
   ```
5. In the setup wizard select **Ollama**, specify the API base URL (e.g. `http://192.168.1.100:11434`), and enter the **exact** model tag. Do not enter the Open WebUI browser address or its browser port instead.
6. Check the model selector within the dashboard. Inference may take longer for models bigger than available RAM/VRAM.

**Open WebUI** may connect to the same Ollama instance, but Open WebUI is optional and Auto Trader communicates directly with Ollama's API. Installed `qwen3-vl` vision models aren't automatically better at numerical prediction.

## B. API models (experimental)

The portable wizard can store a generic **OpenAI-compatible HTTPS** endpoint, completion route, model ID, and API key in private configuration. This does **not** mean every provider uses the same API protocol; native Anthropic Claude and Gemini adapters remain unverified/unimplemented for the current trading workflow.

Examples of values for a compatible provider are an HTTPS API origin, `/v1/chat/completions` route, a supported model name and API key. Verify vendor endpoint conventions and billing separately. Do not give the model broker credentials, session cookies or account identifiers.

Because the underlying trading worker currently defaults to local-model assumptions in some code paths, **do not enable live trading based on external-AI settings until an end-to-end dry run and integration tests pass**. API errors must fail closed.

## C. Separate specialized forecasting service

LightGBM (boosted decision trees), Chronos-Bolt (time series) and FinBERT (financial news sentiment) are **not ordinary Ollama chat model formats**. They run on a separate Python service on the same AI computer. See [Windows AI service installation](../../ai-workstation/README.md).

After starting that service and restricting firewall access to the home server:

```sh
curl --fail --max-time 8 http://192.168.1.100:8766/health
curl --fail --max-time 8 http://192.168.1.100:8766/api/models
curl --fail --max-time 8 http://192.168.1.100:8766/api/forecast
```

Set the optional **Forecast Service URL** in the installer to `http://AI-LAN-IP:8766`. The dashboard's **Next session forecast** view displays the last completed research response and source links.

### Forecast model roles

| Component | Purpose | Important limitation |
| --- | --- | --- |
| LightGBM | Ranks candidates from historical volume/price indicators | Initial chronological holdout **did not beat** a no-change baseline; unvalidated outputs excluded from rank |
| Chronos-Bolt Tiny | Lower / median / upper next-session scenario estimates | Uncalibrated experimental return quantiles, **not** executable prices |
| FinBERT | Positive / neutral / negative classification of recent headlines | Sentiment is not a price prediction; news may be stale or incomplete |
| Qwen / DeepSeek | Optional natural-language research/explanation | LLM agreement is not proof of signal quality |

The service refreshes on startup, after weekday market close, and Monday before the opening bell (New York time). The current scheduler's market-holiday and early-close behavior should be hardened before a public release.

**The forecast has no order-writing permission** and does not change the separate live worker's execution status. It ranks up to five research candidates with dated market data, headline source links, illustrative breakouts/risk invalidation/2R scenarios and explicit unmet confirmations. Do not interpret it as a profit promise.
