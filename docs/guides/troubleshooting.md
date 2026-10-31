# Troubleshooting

**[Docs](../README.md) | [TrueNAS](../install/truenas-scale.md) | [Docker](../install/docker-linux.md) | [AI](ai-setup.md) | [Schwab](schwab.md)**

## First diagnostic steps

```sh
# From the source checkout; adjust persistent directory:
docker compose --env-file /srv/auto-trader-data/config/compose.env \
  -f deploy/docker-compose.yml ps

docker compose --env-file /srv/auto-trader-data/config/compose.env \
  -f deploy/docker-compose.yml logs --tail 100 dashboard

curl -kfsS https://127.0.0.1:8765/health
```

**Never paste raw `config/*.env`, OAuth tokens or account numbers into issues or logs.**

| Symptom | Likely cause / next check |
| --- | --- |
| `git clone` asks for permission / `Repository not found` | Repo remains **private**. Verify user/key is explicitly authorized; use approved SSH/HTTPS credentials |
| `docker compose: command not found` | Install modern Docker Compose plugin; standalone `docker-compose` is not assumed |
| `install.sh` rejects data path | TrueNAS mode requires `/mnt/POOL/...`; Linux Docker uses `--platform docker` and a new writable host path |
| Setup refuses existing configuration | Intentional: existing secrets/ledger are protected. Use backup-aware update steps, not first-install wizard |
| TLS error or certificate warning | Wizard creates self-signed HTTPS certificate. For LAN testing, `curl -k`; for hardened deployment, configure trusted TLS |
| Dashboard unavailable | Check host bind IP, chosen port, Docker `ps`/`logs`, firewall, port conflicts and Compose config |
| Dashboard login fails | Verify entered app password; changing persistent `dashboard.env` requires a planned secret rotation and service recreation |
| Local AI models missing | Query `http://AI-LAN-IP:11434/api/tags` from **the NAS/container**; confirm Ollama binds LAN and correct model tag |
| Model times out | Inspect model size, CPU/GPU capacity, server logs and LAN firewall; try a smaller model |
| Forecast screen says unavailable | Optional Windows research service must be running/reachable on its own LAN port; `GET /health` and `GET /api/forecast` |
| Forecast has no candidate data | Market feed/news temporarily unavailable, model weights still loading, historical bars stale or insufficient; check research service health |
| LightGBM marked unvalidated | **Expected** until chronological holdout beats baseline; do not override gate by treating prediction as a trading signal |
| Schwab OAuth callback mismatch | Confirm developer app's registered HTTPS loopback URL matches installer value; do not paste auth code into support |
| Cannot start live worker | Installation deliberately leaves it disabled; account selection, token checks, reconciliation and separate opt-in are mandatory |
| Container image build fails on ARM NAS | Architecture/dependency compatibility untested. Use supported x86_64 Linux VM or a validated image build |

## Check Ollama vs Open WebUI URLs

Ollama's API is usually at `:11434`. Open WebUI is a separate browser application (port varies). Auto Trader's Ollama connection must use the **Ollama API**, not the Open WebUI browser URL.

## Check TrueNAS model-service networking

From a shell on the **server**, try:

```sh
curl --fail --max-time 8 http://192.168.1.100:11434/api/tags
curl --fail --max-time 8 http://192.168.1.100:8766/health
```

Replace the example IP. Both endpoints should be restricted to trusted LAN clients; do not expose them to public networks.

## Reporting a bug

Provide sanitized steps, OS/version, CPU architecture, selected installation guide, source commit, redacted log excerpt and expected versus observed behavior. Never include account numbers, Schwab developer secrets, dashboard secrets, OAuth tokens, TLS private keys or complete private configuration.
