# Cost Optimization Guide

## Overview

The LLM Gateway includes a **CostOptimizer** module that automatically reduces token usage and controls budget consumption through:

1. **Task-based model routing** — routes simple tasks to cheaper models (Haiku) and complex tasks to more capable models (Sonnet, Opus).
2. **Budget enforcement** — hard stops when an account reaches its budget limit.
3. **Token estimation** — predicts token usage before making a request.
4. **Context window management** — can truncate/summarize long conversations.

## Expected Savings

| Strategy | Typical Savings | How It Works |
|----------|----------------|--------------|
| Task-based routing | 60–80% cheaper for simple tasks | Routes "tell me a joke" to Haiku ($0.25/M) instead of Sonnet ($3/M) |
| Budget enforcement | Prevents overspending | Hard stop at 95% budget usage |
| Token estimation | Avoids over-allocating context | Predicts input/output tokens before request |
| Lazy tool calls | ~10–20% reduction | Skips unnecessary tool invocations |

## Usage

### Start the gateway with cost optimization:

```bash
cd Z:/home/ccdlvc/Working/ccd_plugin/llm_gateway
python -m llm_gateway proxy --host 0.0.0.0 --port 8080
```

### Configure budgets:

```bash
curl -X POST http://localhost:8080/v1/budget/set \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "acc-cheap",
    "limit_usd": 5.0,
    "warning_threshold_pct": 80
  }'
```

### Use cost-aware routing via Claude Code:

```json
{
  "custom_models": [
    {
      "name": "gateway-cost-optimized",
      "endpoint": "http://localhost:8080/v1/messages/completions",
      "model_name": "auto-routing-pool"
    }
  ]
}
```

Then in your prompt, use `model: "auto"` to let the gateway choose:

```json
{
  "messages": [
    {"role": "user", "content": "Tell me a joke about cats"}
  ],
  "max_tokens": 4096,
  "model": "auto"
}
```

The gateway will automatically route to the cheapest model (Haiku) for this simple task.

### Budget reset (admin):

```bash
curl -X POST http://localhost:8080/v1/budget/reset \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "acc-cheap",
    "reset_to": 10.0
  }'
```

## How It Works

### Task Detection → Model Selection

```
User prompt: "What is the capital of France?"
  ↓
Task classifier detects: general knowledge → cheap model (Haiku)
  ↓
Cost: ~$0.00025 (vs. $0.0075 for Sonnet)
```

### Budget Enforcement Flow

```
Request comes in
    ↓
Estimate cost using token prediction
    ↓
Check against budget limits (per account + pool)
    ↓
  ├─ Within budget → Allow request
  └─ Over budget → Return 429 Too Many Requests
```

### Savings Calculation Example

```
Prompt: "Tell me a joke about cats"

Naive routing (always Sonnet):
  Input tokens:     200
  Output tokens:    150
  Cost: 200×3e-6 + 150×15e-6 = $0.000975

Smart routing (Haiku):
  Input tokens:     200
  Output tokens:    150
  Cost: 200×0.25e-6 + 150×1.25e-6 = $0.00025

Savings: $0.000725 per request (74% reduction!)
```

## API Reference

### Set Budget Limit

```bash
POST /v1/budget/set
{
  "account_id": "acc-cheap",
  "limit_usd": 10.0,
  "warning_threshold_pct": 80
}
```

### Get Budget Status

```bash
GET /v1/budget
```

Response:

```json
{
  "budgets": {
    "acc-cheap": {
      "limit_usd": 10.0,
      "spent": 3.42,
      "remaining": 6.58
    }
  }
}
```

### Reset Budget

```bash
POST /v1/budget/reset
{
  "account_id": "acc-cheap",
  "reset_to": 15.0
}
```

## Advanced: Multi-Model Pool

You can configure a pool with multiple models:

```json
{
  "custom_models": [
    {
      "name": "gateway-pool",
      "endpoint": "http://localhost:8080/v1/messages/completions",
      "model_name": "auto-routing-pool"
    }
  ]
}
```

The gateway will maintain a pool of accounts across different models (Haiku, Sonnet, Opus, Codex) and route based on:
1. Task type (code → Codex, math → Sonnet, chat → Haiku)
2. Budget constraints (prefer accounts with remaining budget)
3. Cost efficiency (cheapest capable model first)

## Limitations

- **Token estimation is approximate** — actual token usage may vary by ~±10%
- **Task detection is heuristic-based** — complex prompts may be misclassified
- **Context window management** requires additional configuration (summarization vs. truncation)
- **Budget enforcement is per-account** — you can also set pool-level budgets

## Security Note

This cost optimization does **not** circumvent any rate limits, quotas, or ToS restrictions of the underlying LLM providers. It simply routes among accounts that you legitimately own and control (e.g., your organization's multiple API keys).
