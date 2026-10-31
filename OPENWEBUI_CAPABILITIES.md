# Open WebUI Capability Implementation Tracker

Updated: 2026-10-31. Scope: TrueNAS Open WebUI v0.12.5, Admin PC Ollama, private AutoTrader GitHub repository.

Status definitions: VERIFIED = independently tested; BLOCKED = requires authorized admin access or prerequisites; PLANNED = not installed/tested. No capability is marked complete based on assumption.

| Area | Capability | Status | Acceptance test |
|---|---|---|---|
| Models | Ollama local Qwen3.5 9B, 4B and DeepSeek R1 | VERIFIED on Admin PC only | ollama list shows all three; 9B loaded with mixed CPU/GPU |
| Models | Open WebUI connectivity to Admin PC Ollama | PLANNED | Select model and complete a prompt in Open WebUI |
| Models | Model routing and cloud provider APIs | PLANNED | Fast/reasoning/vision models selected by task |
| Research | Web search with citations | PLANNED | Retrieve current results with source URLs |
| Research | Web page extraction | PLANNED | Read user-specified URL |
| Research | RAG and uploaded documents | PLANNED | Answer with source excerpts |
| Development | GitHub repo SSH fetch/push | VERIFIED on TrueNAS developer workspace | git remote points to Zoncko98/Auto-Trade; previous successful push |
| Development | Open WebUI GitHub read/write tool | BLOCKED | Authenticated Open WebUI admin installs tool; read and create test branch |
| Development | AutoTrader source workspace | VERIFIED on TrueNAS | /home/truenas_admin/autotrade-source-review exists |
| Development | Sandbox terminal/code execution | PLANNED | Run isolated test without host/production access |
| Development | Browser automation | PLANNED | Browser agent completes test on nonproduction site |
| Development | Files and code review | PLANNED | Read/edit/test changes, open PR |
| Documents | PDF, Word, PowerPoint, Excel | PLANNED | Create, reopen and validate each |
| Media | Vision/image generation, STT, TTS | PLANNED | Verify each modality end-to-end |
| Integrations | MCP tool gateway | PLANNED | Tool discovered and invoked with audit log |
| Automation | Scheduled tasks and n8n | PLANNED | Scheduled dry-run, notification and retry |
| Knowledge | Persistent project memory | PLANNED | Retrieval across sessions |
| Operations | Monitoring and backups | PLANNED | Health alert and tested restore |
| AutoTrader | Market data and research | PLANNED | Time-stamped, sourced research |
| AutoTrader | Backtesting and simulated evaluation | PLANNED | Reproducible offline test with transaction costs |
| AutoTrader | AI explanations and trade export | PLANNED | Verify live dashboard outputs, not just source |
| AutoTrader | Live order safety boundary | PLANNED | Confirm no direct Open WebUI order execution |
| AutoTrader | Deployment approval gate | PLANNED | Git changes cannot auto-deploy |

## Access and safety findings

- Open WebUI reachable at http://192.168.1.43:31028, version 0.12.5.
- Open WebUI admin endpoints require authentication.
- TrueNAS truenas_admin SSH account does not have noninteractive sudo or Docker socket access.
- Existing TrueNAS Git workspace has GitHub SSH remote, but that key must NOT be exposed inside Open WebUI or AI-generated code.
- No production container restart, broker connection change, or trading state mutation authorized as part of this checklist.
- Do not use a chat-shared session JWT as a durable API credential. Use a newly generated dedicated admin API key or admin-assisted setup.
- Prefer GitHub branch + pull request workflow rather than direct production deploy.

## Next actions

1. Acquire authorized Open WebUI administrator API access via local secure setup, or complete tool installation in authenticated Admin UI.
2. Provision restricted GitHub tool credentials and branch-only workflow; test against a disposable branch.
3. Connect Ollama endpoint; verify local models from Open WebUI.
4. Implement remaining capabilities in isolated service containers with explicit tests.
