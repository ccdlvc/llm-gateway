# LLM Gateway - Project Summary

## What is this?

**LLM Gateway** is a balance-aware routing proxy for multi-account Claude usage. It allows you to:

- Aggregate balances from multiple Anthropic API accounts into a single "virtual pool"
- Automatically route requests across accounts based on remaining balance, weights, and health
- Maintain sticky sessions so conversation context stays within one account
- Automatically failover when an account is rate-limited or exhausted
- Track costs and usage across all accounts

## File Structure

```
llm_gateway/
├── gateway.py          # Core routing logic, session management, database
├── proxy.py            # Flask HTTP server exposing Anthropic-compatible API
├── cli.py              # Command-line interface for managing accounts
├── run_demo.py         # Interactive demo script
├── run.py              # Simple runner (alias)
├── config.example.yaml # Configuration template
├── requirements.txt    # Runtime dependencies
├── requirements-dev.txt # Dev dependencies
├── setup.py            # Package installation
├── pyproject.toml      # Modern Python packaging config
├── tox.ini             # Test runner configuration
├── Makefile            # Convenient commands
├── README.md           # User documentation
├── DESIGN.md           # Architecture and design details
└── tests/
    └── test_gateway.py  # Unit tests
```

## Quick Start

### Option A: Run as a script (no install needed)

```bash
cd llm_gateway
python run_demo.py
```

This runs an interactive demo showing:
- Virtual pool balance across accounts
- Routing decisions with weighted scoring
- Sticky sessions
- Automatic fallback when accounts are exhausted

### Option B: Run the CLI

```bash
# Register accounts
python -m llm_gateway cli register --name "Team Alpha" --api-key "sk-xxx" --weight 1.0

# List accounts
python -m llm_gateway cli list

# Process a completion
python -m llm_gateway cli complete --session-id "sess-1" --prompt "Hello!"
```

### Option C: Run the proxy server

```bash
cd llm_gateway
pip install -e .
llm-gateway server --port 8080
```

Then configure Claude Code to use `http://localhost:8080/v1/messages/completions` as its endpoint.

## How It Works

### Architecture

```
Claude Code → LLM Gateway (Flask proxy) → Multiple Anthropic Accounts
                │
                ├─ Account Router (weighted scoring + sticky sessions)
                ├─ Virtual Pool (unified balance view)
                ├─ Token Counter & Cost Tracker
                └─ Fallback Manager (automatic failover)
```

### Routing Algorithm

The gateway computes a score for each healthy account:

```
score = (remaining_balance / total_pool) × weight × health_factor × rate_limit_factor × latency_factor
```

**Sticky sessions**: Within a single session, the gateway prefers to keep requests on the same account unless it's exhausted or rate-limited.

### Virtual Pool

The virtual pool presents a unified view:

```json
{
  "pool_name": "Claude Pool",
  "balance_usd": 200.0,
  "tokens_available": 13_333_333_440,
  "accounts": [
    {"id": "acc-1", "name": "Team Alpha", "balance": 100.0},
    {"id": "acc-2", "name": "Team Beta", "balance": 40.0},
    {"id": "acc-3", "name": "Team Gamma", "balance": 60.0}
  ]
}
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| SQLite for storage | Simple, file-based, no external dependency; easy to drop in for production (PostgreSQL) |
| In-memory session state | Low-latency routing decisions; Redis could be added later for distributed scaling |
| Sticky sessions | Conversation context is expensive; keep it within one account when possible |
| Weighted scoring over round-robin | Respects budget constraints while allowing operator control via weights |
| SHA256-hashed API keys in DB | Don't store raw keys; use a secrets manager (e.g., HashiCorp Vault) in production |

## Trade-offs & Limitations

- **Context fragmentation**: If sticky sessions are disabled, conversation context may be split across accounts.
- **Cost estimation is approximate**: The gateway estimates cost based on model pricing; actual billing is done by Anthropic.
- **No built-in auth**: The proxy doesn't authenticate users. In production, add JWT/OAuth2 auth middleware.
- **Single-threaded scoring**: For very high concurrency (>10k req/s), the scoring could be moved to a separate service.

## Future Enhancements

- [ ] Redis backend for distributed session state
- [ ] Prometheus metrics endpoint
- [ ] Webhook notifications when an account is near exhaustion
- [ ] Model affinity routing (route simple queries to cheaper models)
- [ ] Geographic routing (prefer accounts in the same region)
- [ ] Rate limit prediction using machine learning

## License

MIT License — see LICENSE file.
