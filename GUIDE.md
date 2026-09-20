# LLM Gateway — Installation & Usage Guide

## Quick Start

### 1. Install Dependencies

```bash
cd Z:/home/ccdlvc/Working/ccd_plugin/llm_gateway
pip install flask flask-cors
```

### 2. Start the Gateway Server

```bash
python -m llm_gateway proxy --host 0.0.0.0 --port 8080
```

The server will start at `http://localhost:8080` with these endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/messages/completions` | POST | Anthropic-compatible completions API |
| `/v1/pool` | GET | Virtual pool balance |
| `/v1/accounts` | GET/POST/DELETE | Account management |
| `/health` | GET | Health check |

### 3. Configure Claude Code

#### Step A: Install the custom model

Create or edit `~/.claude/codeium`:

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

#### Step B: Restart Claude Code

Close and reopen VS Code (or the CLI app). The gateway will now appear as an available model.

---

## Multi-Model Usage (Claude + Codex + Others)

### 1. Install Multi-Model Gateway

```bash
cd Z:/home/ccdlvc/Working/ccd_plugin/llm_gateway
python -m llm_gateway multi_demo
```

### 2. Configure Multiple Models

Edit `~/.claude/codeium`:

```json
{
  "custom_models": [
    {
      "name": "gateway-llm-pool",
      "endpoint": "http://localhost:8080/v1/messages/completions",
      "model_name": "auto-routing-pool",
      "description": "Auto-routes between Claude, Codex, and other models"
    }
  ],
  "default_model": "gateway-llm-pool"
}
```

### 3. How Routing Works Automatically

When you send a prompt to `gateway-llm-pool`, the gateway:

1. **Detects task type** from your prompt:
   - Code-related → routes to **Codex** (cheapest for code)
   - Reasoning / math → routes to **Claude-3.5-Sonnet**
   - Creative writing → routes to **Claude-3.5-Sonnet**
   - General chat → routes to **Claude-3-Haiku** (cheapest)

2. **Within each model**, it selects the account with:
   - Most remaining balance
   - Best health score
   - Lowest latency
   - Respectful of rate limits

3. **Sticky sessions**: Once a task starts on a model, it stays on that model for the conversation.

### 4. Example Session

```
User: "Write a Python function to compute fibonacci(n)"
  → Detected as: code_generation
  → Routed to: Codex (cost: $0.0000002)

User: "Explain quantum entanglement"
  → Detected as: reasoning
  → Routed to: Claude-3.5-Sonnet (cost: $0.00048)

User: "Tell me a joke about cats"
  → Detected as: general_chat
  → Routed to: Claude-3-Haiku (cost: $0.00009)
```

---

## Using with External LLMs (Ollama, vLLM, etc.)

You can also route to local models like Ollama or vLLM:

### Add Ollama Model

```json
{
  "custom_models": [
    {
      "name": "ollama-codex",
      "endpoint": "http://localhost:11434/api/generate",
      "model_name": "codellama:7b",
      "cost_per_token_input": 0.0,
      "cost_per_token_output": 0.0,
      "context_window": 4096,
      "max_tokens": 2048,
      "enabled": true
    },
    {
      "name": "ollama-llama3",
      "endpoint": "http://localhost:11434/api/generate",
      "model_name": "llama3:8b",
      "cost_per_token_input": 0.0,
      "cost_per_token_output": 0.0,
      "context_window": 8192,
      "max_tokens": 4096,
      "enabled": true
    }
  ]
}
```

Then update the gateway to support Ollama's `/api/generate` format.

---

## Environment Variables

Set these before running:

```bash
export CLAUDE_GATEWAY_HOST=0.0.0.0
export CLAUDE_GATEWAY_PORT=8080
export CLAUDE_GATEWAY_DB_PATH=./gateway.db
export CLAUDE_GATEWAY_DEBUG=true
```

---

## API Reference

### Completions

```bash
curl -X POST http://localhost:8080/v1/messages/completions \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "sess-abc",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "max_tokens": 4096
  }'
```

### Pool Status

```bash
curl http://localhost:8080/v1/pool
```

### Account Management

```bash
# Register a new account
curl -X POST http://localhost:8080/v1/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Team Account",
    "api_key": "sk-ant-xxx",
    "weight": 2.0,
    "remaining_balance": 50.0
  }'

# List accounts
curl http://localhost:8080/v1/accounts

# Unregister
curl -X DELETE http://localhost:8080/v1/accounts/my-team-acc
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No available models" | Check that `custom_models` is configured in `~/.claude/codeium` |
| "Model not found" | Verify the model name matches what's registered in the gateway |
| Connection refused | Ensure the gateway server is running (`python proxy.py`) |
| 401 Unauthorized | Your API key is invalid or expired |

---

## License

MIT License — see LICENSE file.
