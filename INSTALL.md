# Installation & Usage Guide

## Prerequisites

- Python 3.9+
- `pip` installed

## Step-by-Step Installation

### 1. Navigate to the project

```bash
cd Z:/home/ccdlvc/Working/ccd_plugin/llm_gateway
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Start the gateway server

```bash
python -m llm_gateway proxy --host 0.0.0.0 --port 8080
```

You should see:

```
Starting LLM Gateway Proxy on http://0.0.0.0:8080
 * Running on http://0.0.0.0:8080
```

### 4. Configure Claude Code

Create/edit `~/.claude/codeium`:

```json
{
  "custom_models": [
    {
      "name": "llm-gateway",
      "endpoint": "http://localhost:8080/v1/messages/completions",
      "model_name": "gateway-pool",
      "description": "Multi-account Claude pool with balance-aware routing"
    }
  ],
  "default_model": "llm-gateway"
}
```

### 5. Restart Claude Code / VS Code

Close and reopen VS Code. The gateway model will now appear in the model selection dropdown.

---

## Running the Demo (No Server Needed)

```bash
python -m llm_gateway demo
```

This runs an interactive demo showing:
- Virtual pool balance aggregation
- Weighted routing across accounts
- Sticky session behavior
- Automatic failover

---

## Multi-Model Setup

To use **Claude + Codex + other models** in one session:

### 1. Create a multi-model config

Edit `~/.claude/codeium`:

```json
{
  "custom_models": [
    {
      "name": "gateway-multi",
      "endpoint": "http://localhost:8080/v1/messages/completions",
      "model_name": "auto-routing-pool"
    }
  ],
  "default_model": "gateway-multi"
}
```

### 2. Start the multi-model gateway

```bash
python -m llm_gateway multi_demo
```

This registers:
- **Claude-3.5-Sonnet** → for reasoning, coding, general tasks
- **Codex** → for code generation (cheapest)
- **Claude-3-Haiku** → for simple chat (cheapest)

The gateway automatically routes based on task detection.

---

## Adding Your Own Accounts

### Register an Anthropic Account

```bash
python -m llm_gateway cli register \
  --name "My Team Account" \
  --api-key "sk-ant-your-api-key" \
  --weight 1.0 \
  --base-url "https://api.anthropic.com/v1/messages"
```

### List All Accounts

```bash
python -m llm_gateway cli list
```

### Add Balance to the Pool

```bash
python -m llm_gateway cli add-balance --amount 50.0
```

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│                    Claude Code User                        │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
    ┌─────────────────────────────────────────────┐
    │   ~/.claude/codeium (configuration)          │
    │   custom_models: [                           │
    │     name: "llm-gateway",                     │
    │     endpoint: "http://localhost:8080/v1/..." │
    │   ]                                          │
    └──────────────────────┬───────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────┐
    │        LLM Gateway (Flask Server)            │
    │                                               │
    │  ┌─────────────────────────────────────┐    │
    │  │  Multi-Model Router                 │    │
    │  │  • Task type detection              │    │
    │  │  • Model affinity routing           │    │
    │  │  • Balance-aware account selection  │    │
    │  │  • Sticky sessions                  │    │
    │  └─────────────────────────────────────┘    │
    │                                               │
    │  ┌─────────────────────────────────────┐    │
    │  │  Virtual Pool Manager                │    │
    │  │  • Unified balance view             │    │
    │  │  • Cost aggregation                  │    │
    │  └─────────────────────────────────────┘    │
    │                                               │
    │  ┌─────────────────────────────────────┐    │
    │  │  Account Registry (SQLite)          │    │
    │  │  • Balance tracking                  │    │
    │  │  • Health monitoring                 │    │
    │  │  • Rate limit tracking               │    │
    │  └─────────────────────────────────────┘    │
    └──────────────────────┬───────────────────────┘
                           │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   Claude-3.5    Claude-Haiku      Codex /
   (reasoning)   (cheap chat)       Ollama models
          │               │               │
          └──────────────┴───────────────┘
```

---

## FAQ

**Q: How do I add a new model?**  
A: Edit `~/.claude/codeium` and add a new entry to `custom_models`. The gateway auto-detects the model type based on the endpoint.

**Q: Can I use this with Ollama / local models?**  
A: Yes — register them as custom models pointing to `http://localhost:11434/api/generate`. The gateway can forward requests to any compatible API.

**Q: How does it know which model to use?**  
A: It uses prompt-based task detection (code keywords → Codex, math keywords → Claude-3.5, etc.) plus configurable weights.

**Q: What happens if all accounts are exhausted?**  
A: The gateway returns an error with the remaining balance in the virtual pool, and you can add more funds via `cli add-balance`.

**Q: Is this legal / ToS-compliant?**  
A: This is designed for legitimate use cases:
- Multi-team organizations pooling their API budgets
- Shared budget across projects
- Multi-region deployments with geographic routing
- Cost optimization within your own paid quotas

It does **not** circumvent rate limits or attempt to abuse the service. It simply routes among accounts you legitimately own.

---

## License

MIT License — see LICENSE file.
