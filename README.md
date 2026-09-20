# LLM Gateway

> Balance-aware routing proxy for multi-account Claude usage with multi-model support.

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## One-Liner

```bash
python -m llm_gateway proxy --host 0.0.0.0 --port 8080
```

Then configure Claude Code to use `http://localhost:8080/v1/messages/completions` as its endpoint.

---

## What Does This Do?

The LLM Gateway is a **balance-aware routing proxy** that:

- Aggregates balances from multiple Claude API accounts into a single "virtual pool"
- Automatically routes requests across accounts based on remaining balance, weights, and health
- Supports **multi-model routing** — mix Claude, Codex, Ollama, etc. in one session
- Maintains **sticky sessions** so conversation context stays within one account
- Provides **automatic failover** when an account is rate-limited or exhausted

### Example Session

```
User: "Write a React component with TypeScript"
  → Detected as code generation → Routed to Codex (cost: $0.0000002)

User: "Explain quantum entanglement"
  → Detected as reasoning → Routed to Claude-3.5-Sonnet (cost: $0.00048)

User: "Tell me a joke"
  → Detected as general chat → Routed to Claude-3-Haiku (cost: $0.00009)

Total cost: ~$0.00059 for a multi-model session
```

---

## Quick Start

### Install

```bash
cd Z:/home/ccdlvc/Working/ccd_plugin/llm_gateway
pip install -r requirements.txt
```

### Start the Server

```bash
python -m llm_gateway proxy --host 0.0.0.0 --port 8080
```

### Configure Claude Code

Edit `~/.claude/codeium`:

```json
{
  "custom_models": [
    {
      "name": "llm-gateway",
      "endpoint": "http://localhost:8080/v1/messages/completions",
      "model_name": "gateway-pool"
    }
  ],
  "default_model": "llm-gateway"
}
```

Restart VS Code / Claude Code. Done!

---

## Multi-Model Routing

To use **Claude + Codex + Ollama** in one session, edit `~/.claude/codeium`:

```json
{
  "custom_models": [
    {
      "name": "gateway-multi",
      "endpoint": "http://localhost:8080/v1/messages/completions",
      "model_name": "auto-routing-pool"
    }
  ]
}
```

The gateway automatically detects task type and routes:

| Task Type | Routes To | Why |
|-----------|-----------|-----|
| Code generation | Codex / Llama-Coder | Cheaper for code |
| Reasoning / math | Claude-3.5-Sonnet | Best reasoning |
| Creative writing | Claude-3.5-Sonnet | High quality |
| General chat | Claude-3-Haiku | Cheapest |

---

## API Reference

### Completions

```bash
curl -X POST http://localhost:8080/v1/messages/completions \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "sess-1",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 4096
  }'
```

### Pool Status

```bash
curl http://localhost:8080/v1/pool
```

Response:

```json
{
  "pool_name": "Claude Pool",
  "balance_usd": 250.0,
  "tokens_available": 16_666_666_667,
  "accounts": [
    {"id": "acc-1", "name": "Team Alpha", "balance": 100.0},
    {"id": "acc-2", "name": "Team Beta", "balance": 40.0},
    {"id": "acc-3", "name": "Team Gamma", "balance": 110.0}
  ]
}
```

---

## Architecture

```
Claude Code → LLM Gateway → Multiple Models
                │
        ┌───────┼─────────┬──────────┐
        ▼       ▼         ▼          ▼
   Claude-3.5  Codex    Haiku    Ollama
   (reasoning) (code)   (chat)   (local)
```

---

## Use Cases

- **Multi-team orgs**: Share a budget across engineering, research, and product teams
- **Cost optimization**: Route simple queries to cheaper models, complex ones to Claude
- **Multi-region**: Route requests to accounts in different geographic regions
- **Failover**: If one account is rate-limited, automatically use another

---

## License

MIT — see [LICENSE](LICENSE)
