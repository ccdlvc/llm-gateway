# LLM Gateway - Design Document

## Overview

LLM Gateway is a balance-aware routing proxy for multi-account Claude usage. It intercepts requests from Claude Code (or any Anthropic-compatible client) and intelligently routes them across multiple API accounts based on remaining balance, weights, health status, and latency.

## Problem Statement

Teams and organizations often have multiple Claude API accounts with different balances. The goal is to:

1. **Pool** — Aggregate balances from multiple accounts into a unified "virtual pool"
2. **Route** — Automatically route requests to the account with the most available capacity
3. **Sticky sessions** — Keep conversation context within one account to avoid context fragmentation
4. **Failover** — Automatically switch accounts when one is rate-limited or exhausted
5. **Cost tracking** — Track spending per account and across the pool

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        LLM Gateway                                │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐       │
│  │                    Account Router                      │       │
│  │  ┌──────────────────────────────────────────────────┐ │       │
│  │  │  Weighted Scoring Algorithm                       │ │       │
│  │  │    score = balance × weight × health × rate_limit │ │       │
│  │  └──────────────────────────────────────────────────┘ │       │
│  │  ┌──────────────────────────────────────────────────┐ │       │
│  │  │  Sticky Session Manager                           │ │       │
│  │  │    • Tracks conversation history per session      │ │       │
│  │  │    • Prefers same account within a session        │ │       │
│  │  └──────────────────────────────────────────────────┘ │       │
│  │  ┌──────────────────────────────────────────────────┐ │       │
│  │  │  Fallback Manager                                 │ │       │
│  │  │    • Detects rate limits / errors                  │ │       │
│  │  │    • Selects next best account                     │ │       │
│  │  └──────────────────────────────────────────────────┘ │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐       │
│  │                    Virtual Pool                        │       │
│  │  • Unified balance view across all accounts            │       │
│  │  • Aggregate token usage tracking                       │       │
│  │  • Cost aggregation                                    │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐       │
│  │                    Token Counter                        │       │
│  │  • Tracks tokens_in / tokens_out per account           │       │
│  │  • Estimates remaining capacity                         │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐       │
│  │                    Health Monitor                        │       │
│  │  • Rate limit detection                                 │       │
│  │  • Latency tracking (for scoring)                       │       │
│  │  • Error tracking                                       │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐       │
│  │                    Database Layer                        │       │
│  │  • accounts (SQL)                                       │       │
│  │  • sessions                                              │       │
│  │  • request_log (audit trail)                            │       │
│  │  • budget_limits                                         │       │
│  └──────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘

    ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Claude Code / Client                       │
│                        (via proxy: http://gateway:8080)          │
└─────────────────────────────────────────────────────────────────┘
```

## Routing Algorithm

### Scoring Formula

For each healthy account, compute a score:

```
score = base_score × health_factor × rate_limit_factor × latency_factor

where:
  base_score   = remaining_balance / total_pool_balance × weight
  health_factor = 1.0 (healthy) or 0.3 (rate-limited) or 0.5 (maintenance)
  rate_limit_factor = min(1.0, (max_requests - recent_requests) / max_requests)
  latency_factor   = max(0.5, 1.0 - (avg_latency - 1.0) / 2.0)
```

### Decision Flow

```
┌────────────────────────────────────────────┐
│  Is this a sticky session?                  │
│  (i.e., does the session have prior turns?) │
└────────────────────────────────────────────┘
           │
        ┌──┴───┐
       Yes │   │ No
           ▼   ▼
    ┌─────────────────┐   ┌────────────────────┐
    │ Is current      │   │ Compute scores for  │
    │ account healthy?│   │ all healthy accounts│
    └─────────────────┘   └────────────────────┘
           │                    │
        Yes│                  ▼
           ▼          ┌─────────────────┐
    Use current     │ Score all         │
    account         │ healthy accounts  │
                   └──────────┬─────────┘
                             │
                     ┌───────▼───────┐
                     │ Any healthy   │
                     │ accounts left?│
                     └───────┬───────┘
             Yes │          │ No
             ┌───▼──┐   ┌───▼──┐
            Use     │  │ No    │
            current │  │       ▼
            account │  │  Return
                   │  │  error:
                   ▼  │  "no healthy accounts"
          ┌───────────┐
         Update usage
```

## Data Model

### Database Schema (SQLite)

```sql
-- Accounts table
CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    api_key_hash TEXT NOT NULL,       -- SHA256 of the actual key
    base_url TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'claude-3-5-sonnet-20241022',
    max_tokens INTEGER NOT NULL DEFAULT 8192,
    weight REAL NOT NULL DEFAULT 1.0,
    enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'healthy',
    remaining_balance REAL NOT NULL DEFAULT 0.0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    last_used TEXT
);

-- Sessions table
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    current_account_id TEXT,
    total_tokens_used INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0.0
);

-- Request log (audit trail)
CREATE TABLE request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt TEXT NOT NULL,
    response_text TEXT,
    usage_input_tokens INTEGER,
    usage_output_tokens INTEGER,
    cost_usd REAL,
    latency_ms REAL,
    error TEXT,
    timestamp REAL NOT NULL
);

-- Budget limits
CREATE TABLE budget_limits (
    account_id TEXT PRIMARY KEY,
    limit_usd REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL
);
```

## API Reference

### Completions (Chat-style)

```bash
POST /v1/messages/completions
Content-Type: application/json

{
  "session_id": "sess-abc123",
  "messages": [
    {"role": "user", "content": "Hello!"},
    {"role": "assistant", "content": "Hi! How can I help?"},
    {"role": "user", "content": "Tell me a joke."}
  ],
  "max_tokens": 4096,
  "model": "claude-3-5-sonnet-20241022"
}

Response:
{
  "id": "acc-1-msg-xxx",
  "type": "message",
  "role": "assistant",
  "content": [
    {"type": "text", "text": "[ROUTED TO Team Alpha] ..."}
  ],
  "model": "claude-3-5-sonnet-20241022",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 256,
    "output_tokens": 128
  },
  "cost": 0.000328
}
```

### Pool Status

```bash
GET /v1/pool

Response:
{
  "pool_name": "Claude Pool",
  "balance_usd": 200.0,
  "tokens_available": 13333333440,
  "tokens_used": 5120,
  "accounts": [
    {"id": "acc-1", "name": "Team Alpha", "balance": 100.0},
    {"id": "acc-2", "name": "Team Beta", "balance": 40.0},
    {"id": "acc-3", "name": "Team Gamma", "balance": 160.0}
  ]
}
```

### Account Management

```bash
# Register an account
POST /v1/accounts
{
  "name": "Team Alpha",
  "api_key": "sk-ant-xxxx...",
  "weight": 2.0,
  "model": "claude-3-5-sonnet-20241022"
}

# List accounts
GET /v1/accounts

# Unregister
DELETE /v1/accounts/{account_id}
```

## Usage Scenarios

### Scenario 1: Multi-team Organization

- **Team Alpha**: $100 balance, weight=1.0 → gets ~33% of requests
- **Team Beta**: $40 balance, weight=1.0 → gets ~13% of requests
- **Team Gamma**: $160 balance, weight=1.0 → gets ~54% of requests

As Team Alpha's balance depletes, its share decreases proportionally.

### Scenario 2: Budget Control

Set per-account budgets:

```bash
llm-gateway cli budget --account-id acc-1 --limit 50.0
```

When Account 1 hits $50, it's temporarily excluded from routing until the limit is reset or manually adjusted.

### Scenario 3: Failover

When Account A is rate-limited (429 error), the gateway automatically routes to the next best account. The failed request is retried on a different account if available.

### Scenario 4: Virtual Pool for Shared Budget

Multiple individuals contribute their API keys to a shared pool. Each sees only their personal balance in their own Claude instance, but the gateway presents a unified view for budgeting purposes.

## Security Considerations

1. **API Key Storage**: Keys are stored as SHA256 hashes in the database. The actual keys are kept in environment variables or a separate secrets store.

2. **Rate Limiting**: Each account has its own rate limit window. The gateway tracks requests per window and can throttle or fail fast.

3. **Audit Trail**: All requests are logged with session_id, account_id, prompt (truncated), and response metadata for compliance.

4. **Network Isolation**: Consider running the gateway on a separate VPC/subnet with strict network policies.

## Performance Considerations

- **Database**: SQLite is fine for < 10k concurrent sessions. For higher scale, switch to PostgreSQL/Redis.
- **Scoring**: The scoring algorithm is O(n) where n = number of accounts. For > 100 accounts, consider pre-computed scores with Redis.
- **Session state**: Currently stored in-memory. For distributed deployments, use Redis for shared session state.

## Limitations & Trade-offs

| Concern | Approach | Trade-off |
|---------|----------|-----------|
| Context fragmentation | Sticky sessions | Single account handles entire conversation; may waste balance on short conversations |
| Cost estimation | Approximate based on model pricing | Actual cost is only known after response returns |
| Rate limit detection | Retry + error parsing | May retry on transient errors before detecting rate limit |
| Latency tracking | In-memory history | Only works for single-instance deployments |

## Future Enhancements

- [ ] **Redis backend** for distributed state (shared sessions across multiple gateway instances)
- [ ] **Prometheus metrics** endpoint
- [ ] **Webhook notifications** when an account is about to be exhausted
- [ ] **Model affinity routing** — route simple queries to cheaper models
- [ ] **Geographic routing** — prefer accounts in the same region as the user
- [ ] **Cost optimization mode** — prefer cheaper models when budget is low
