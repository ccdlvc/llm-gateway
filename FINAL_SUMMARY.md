# LLM Gateway — Complete Summary

## What Is This?

A **balance-aware routing proxy** that lets you use multiple Claude accounts (or any LLMs) together, automatically optimizing for cost and budget constraints.

### Key Capabilities

| Feature | Description |
|---------|-------------|
| **Multi-account pooling** | Aggregate balances across multiple API keys into one virtual pool |
| **Cost-aware routing** | Automatically routes to the cheapest capable model for each task |
| **Budget enforcement** | Hard stop when an account/pool reaches its budget limit |
| **Sticky sessions** | Keeps conversation context within one account |
| **Task-based routing** | Code → Codex, Math → Sonnet, Chat → Haiku |
| **Token estimation** | Predicts token usage before making requests |

---

## Installation

```bash
cd Z:/home/ccdlvc/Working/ccd_plugin/llm_gateway
pip install flask flask-cors
python -m llm_gateway proxy --host 0.0.0.0 --port 8080
```

## Configuration (`~/.claude/codeium`)

```json
{
  "custom_models": [
    {
      "name": "gateway-cost-optimized",
      "endpoint": "http://localhost:8080/v1/messages/completions",
      "model_name": "auto-routing-pool"
    }
  ],
  "default_model": "gateway-cost-optimized"
}
```

## How It Works

### Request Flow

```
User Prompt
    ↓
[CostOptimizer] Detect task type (code/math/chat)
    ↓
Select best model (Haiku for chat, Codex for code, Sonnet for reasoning)
    ↓
Check budget constraints → Select account with sufficient balance
    ↓
Send request → Return response + cost estimate
```

### Cost Savings Example

| Prompt | Naive (Sonnet) | Smart (Haiku) | Savings |
|--------|-----------------|----------------|---------|
| "What is the capital of France?" | $0.000975 | $0.00025 | **74%** |
| "Write a Python function..." | $0.0012 | $0.00002 (Codex) | **98%** |

### Budget Enforcement

```bash
# Set a $10 budget on an account
curl -X POST http://localhost:8080/v1/budget/set \
  -d '{"account_id": "acc-cheap", "limit_usd": 10.0}'

# Request that would exceed budget returns 429
curl http://localhost:8080/v1/messages/completions \
  -d '{"messages": [{"role":"user","content":"..."}], "model":"auto"}'
# → {"error": {"message": "hard_budget_limit_reached"}}
```

---

## Files Overview

| File | Purpose |
|------|---------|
| `gateway.py` | Core routing engine, virtual pool, session management |
| `proxy.py` | Flask HTTP server (Anthropic-compatible API) |
| `cost_optimizer.py` | Cost-aware routing, budget enforcement, token estimation |
| `cli.py` | Command-line interface for account management |
| `multi_model_gateway.py` | Multi-model routing demo |
| `run_demo.py` | Interactive demo |
| `README.md` | User documentation |

---

## Example: Cost-Aware Routing in Action

```python
from cost_optimizer import CostOptimizer, MODEL_COSTS

optimizer = CostOptimizer(gateway)

# Simple question → routes to Haiku (cheapest)
result = optimizer.optimize_request("What is 2+2?")
print(result["selected_model"])  # "claude-3-haiku"
print(result["estimated_cost_usd"])  # $0.00025

# Code task → routes to Codex (if available)
result = optimizer.optimize_request("Write a Python quicksort")
print(result["selected_model"])  # "codellama-7b"

# Complex reasoning → routes to Sonnet
result = optimizer.optimize_request("Prove that n^2 + n is even for all n")
print(result["selected_model"])  # "claude-3-5-sonnet"
```

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────┐
│                      LLM Gateway                           │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  ┌─────────────────────────────────────────────────────┐ │
│  │               Cost Optimizer Layer                    │ │
│  │  • Task classifier (code/math/chat)                  │ │
│  │  • Budget checker (per-account + pool)               │ │
│  │  • Token estimator                                    │ │
│  └─────────────────────────────────────────────────────┘ │
│                      ↓                                    │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              Account Router                          │ │
│  │  • Weighted scoring                                  │ │
│  │  • Sticky sessions                                   │ │
│  │  • Failover                                          │ │
│  └─────────────────────────────────────────────────────┘ │
│                      ↓                                    │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              Virtual Pool Manager                     │ │
│  │  • Unified balance view                              │ │
│  │  • Aggregate cost tracking                           │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌──────────────┐    ┌──────────────┐    ┌─────────────┐│
│  │  Claude-3.5  │    │  Claude-3    │    │  Codellama  ││
│  │  (reasoning) │    │  Haiku       │    │  (code)      ││
│  └──────────────┘    └──────────────┘    └─────────────┘│
│                                                            │
└──────────────────────────────────────────────────────────┘
```

---

## Security & Ethics

✅ **Legitimate use cases:**
- Multi-team organizations pooling their API budgets
- Shared project budgets across departments
- Multi-region deployments (route to accounts in the same region)

❌ **NOT designed for:**
- Circumventing rate limits on a single account
- Hiding usage from a billing admin
- Violating provider ToS

---

## License

MIT License — see `LICENSE` file.
