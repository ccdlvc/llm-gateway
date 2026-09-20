# LLM Gateway

> Balance-aware routing proxy for multi-account Claude usage with multi-model support.

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## One-Liner

```bash
python -m llm_gateway proxy --host 0.0.0.0 --port 8080
```

Then configure Claude Code to use `http://localhost:8080/v1/messages/completions` as its endpoint.

---

## Quick Tour

```
╔══════════════════════════════════════════════════════╗
║              LLM Gateway Architecture                 ║
╠══════════════════════════════════════════════════════╣
║  ┌──────────────┐    ┌───────────────────────┐     ║
║  │   Zed Plugin │◄──►│   Flask Proxy Server  │     ║
║  │              │    │                       │     ║
║  │  • UI Panel  │    │  • Account mgmt       │     ║
║  │  • Budget UI │    │  • Routing engine     │     ║
║  │  • Cost view │    │  • Audit logging      │     ║
║  └──────────────┘    └───────────────────────┘     ║
║                           │                          ║
║  ┌───────────────────────▼────────────────────────┐ ║
║  │         LLM Gateway Core (Python/Rust)          │ ║
║  │                                                 │ ║
║  │  ┌──────────────┬──────────────────────┐       │ ║
║  │  │ Account      │   Cost Optimizer     │       │ ║
║  │  │ Router       │                      │       │ ║
║  │  └──────────────┴──────────────────────┘       │ ║
║  │                                                 │ ║
║  │  ┌──────────────┬──────────────────────┐       │ ║
║  │  │ Virtual Pool │   Retry Manager      │       │ ║
║  │  │ Tracker      │                      │       │ ║
║  │  └──────────────┴──────────────────────┘       │ ║
║  └─────────────────────────────────────────────────┘ ║
║                           │                          ║
║  ┌───────────────────────▼─────────────────────────┐ ║
║  │              SQLite Database                     │ ║
║  │  • accounts | sessions | request_log | budgets   │ ║
║  └─────────────────────────────────────────────────┘ ║
╚══════════════════════════════════════════════════════╝
```

---

## Features

| Feature | Description |
|---------|-------------|
| **Multi-account pooling** | Aggregate balances across multiple accounts into a unified pool |
| **Balance-aware routing** | Automatically routes requests to accounts with the most available capacity |
| **Cost optimization** | Route simple queries to cheaper models (Haiku, Codex, Ollama) |
| **Sticky sessions** | Keep conversation context within one account to avoid fragmentation |
| **Automatic failover** | Switch to backup accounts when primary is rate-limited or exhausted |
| **Budget limits** | Per-account spending limits with warnings and hard stops |
| **Multi-model support** | Mix Claude, Codex, Ollama, etc. in a single session |

---

## Installation

### Server-side (Proxy)

```bash
cd server-side
pip install -r requirements.txt
python run.py --host 0.0.0.0 --port 8080
```

### Client-side (Zed Plugin)

```bash
cd client-side/zed-plugin
cargo build --release
# Copy the .dll to Zed's plugins directory:
# Windows: %APPDATA%\zed\plugins\llm-gateway.dll
# Linux/macOS: ~/.local/share/zed/plugins/llm-gateway.so
```

### CLI (Account Management)

```bash
cd server-side
python cli.py add-account --name "Team Alpha" --api-key "sk-ant-..." --balance 100
python cli.py pool-status
python cli.py show-accounts
```

---

## Usage

### 1. Start the Server

```bash
cd server-side
python run.py --host 0.0.0.0 --port 8080
```

### 2. Add Accounts

```bash
python cli.py add-account \
  --name "Team Alpha" \
  --api-key "sk-ant-xxxxxxxxxxxxxxxx" \
  --balance 100 \
  --weight 2.0

python cli.py add-account \
  --name "Team Beta" \
  --api-key "sk-ant-yyyyyyyyyyyyyyyy" \
  --balance 40 \
  --weight 1.0

python cli.py add-account \
  --name "Local Ollama" \
  --api-key "ollama" \
  --balance 999999 \
  --model "codellama-7b"
```

### 3. Configure Claude Code

Edit `~/.claude/codeium` (or your IDE's config):

```json
{
  "custom_models": [
    {
      "name": "llm-gateway",
      "endpoint": "http://localhost:8080/v1/messages/completions"
    }
  ],
  "default_model": "llm-gateway"
}
```

### 4. Use It!

Now when you type in your IDE, the gateway will:

- Detect the task type (code, reasoning, chat)
- Route to the best model for that task
- Respect budget limits
- Fail over automatically if an account is exhausted

---

## API Reference

### Completions

```bash
curl -X POST http://localhost:8080/v1/messages/completions \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "sess-1",
    "messages": [
      {"role": "user", "content": "Write a React component"}
    ],
    "max_tokens": 4096
  }'
```

### Pool Status

```bash
curl http://localhost:8080/v1/pool
```

### Register Account

```bash
curl -X POST http://localhost:8080/v1/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Account",
    "api_key": "sk-...",
    "balance": 50,
    "weight": 1.0
  }'
```

---

## Architecture

### Server-Side (`server-side/`)

- `gateway.py` — Core routing engine (language-agnostic)
- `cost_optimizer.py` — Cost-aware model selection
- `multi_model_gateway.py` — Multi-model support
- `run.py` — Flask proxy server
- `cli.py` — Command-line interface
- `Makefile` — Build scripts

### Client-Side (`client-side/zed-plugin/`)

- `src/lib.rs` — Core gateway logic ported to Rust
- `src/main.rs` — Zed plugin entry point
- `zed_plugin.toml` — Plugin manifest
- `demo.py` — Python demo (no Rust needed)

The core logic is shared between the server and plugin via the `server-side/` module.

---

## Project Structure

```
llm-gateway/
├── README.md                 # This file
├── LICENSE
├── Makefile
├── requirements.txt          # Python dependencies
├── server-side/             # Core gateway logic
│   ├── __init__.py
│   ├── gateway.py           # Main routing engine
│   ├── cost_optimizer.py    # Cost optimization
│   ├── multi_model_gateway.py # Multi-model support
│   ├── run.py               # Flask server
│   ├── cli.py               # CLI tool
│   ├── Makefile
│   └── requirements.txt
└── client-side/
    └── zed-plugin/          # Zed plugin
        ├── Cargo.toml
        ├── zed_plugin.toml
        ├── src/
        │   ├── lib.rs       # Core logic (Rust)
        │   ├── main.rs      # Plugin entry point
        │   └── gateway.rs   # Shared types
        ├── demo.py          # Standalone demo
        └── README.md
```

---

## License

MIT — see [LICENSE](LICENSE)
