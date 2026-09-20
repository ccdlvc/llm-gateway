# Refactoring Summary: LLM Gateway → Zed Plugin

## What Was Done

The original monolithic Flask-based proxy has been refactored into a **two-tier architecture**:

```
server-side/     → Core gateway logic (language-agnostic Python/Rust)
client-side/zed-plugin/  → Zed plugin (Rust)
```

---

## File Structure

### Server-Side (`server-side/`)

| File | Purpose |
|------|---------|
| `gateway.py` | Core routing engine — balance-aware routing, account management, virtual pool |
| `cost_optimizer.py` | Cost optimization logic — model selection based on task type, budget enforcement |
| `multi_model_gateway.py` | Multi-model support — routes between Claude, Codex, Ollama, etc. |
| `run.py` | Flask proxy server (optional HTTP interface) |
| `cli.py` | Command-line tool for managing accounts and budgets |
| `requirements.txt` | Python dependencies (`flask`, `flask-cors`, `pydantic`) |
| `Makefile` | Build scripts for quick commands |

### Client-Side (`client-side/zed-plugin/`)

| File | Purpose |
|------|---------|
| `Cargo.toml` | Rust dependencies |
| `zed_plugin.toml` | Zed plugin manifest |
| `src/lib.rs` | Core gateway logic ported to Rust (shared with server) |
| `src/main.rs` | Plugin entry point — hooks into Zed's LLM client API |
| `demo.py` | Python demo that runs without Rust (for quick testing) |
| `README.md` | Plugin documentation |

---

## Key Design Decisions

### 1. Shared Core Logic

The `server-side/gateway.py` contains the core routing logic:

- `AccountRouter` — balance-aware routing algorithm
- `BalanceTracker` — virtual pool management
- `TokenCounter` — cost estimation
- `LLMGateway` — main orchestration class

This same logic is ported to Rust in `client-side/zed-plugin/src/gateway.rs` for the plugin.

### 2. Zed Plugin Architecture

The plugin is a **background process** that:

1. Loads account configurations from Zed's settings
2. Maintains an in-memory state of accounts and budgets
3. Intercepts LLM requests via Zed's `llm_client` API
4. Routes requests through the gateway logic
5. Displays a panel showing pool balance and costs

### 3. Server as Optional HTTP Proxy

The Flask server (`run.py`) is **optional**. The plugin can operate entirely in-process without a separate server process. This makes it ideal for:

- Local development (no network hop)
- Distributed deployments (multiple plugins sharing state via Redis)
- Embedded usage (IDEs that want the routing logic but don't need a server)

---

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                     User types in Zed                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Zed LLM Client Hook                          │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  Intercepts the request:                               │   │
│  │    • Captures the prompt                               │   │
│  │    • Extracts session_id (from chat history)           │   │
│  │    • Determines task type (code, reasoning, chat)      │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  LLM Gateway (Rust)                           │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  AccountRouter.route_request(session_id, prompt)       │   │
│  │    1. Check sticky sessions → prefer current account   │   │
│  │    2. Score all healthy accounts by balance/weight     │   │
│  │    3. Apply budget constraints                          │   │
│  │    4. Select best account                               │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  CostOptimizer.select_model_for_task(prompt)            │   │
│  │    • Code → Codex / Ollama                              │   │
│  │    • Reasoning → Claude-3.5-Sonnet                      │   │
│  │    • Chat → Claude-3-Haiku                              │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Route request to the selected model (via Zed's config)      │
│  • If using custom_models: forwards to the endpoint           │
│  • If using built-in models: uses Zed's native client         │
└─────────────────────────────────────────────────────────────┘
```

---

## Usage Examples

### Running the Demo (no build needed)

```bash
cd client-side/zed-plugin
python demo.py
```

Output:
```
╔══════════════════════════════════════════════════════╗
║   LLM Gateway - Zed Plugin (Standalone Demo)        ║
╚══════════════════════════════════════════════════════╝

📊 Virtual Pool Balance:
{
  "pool_name": "LLM Gateway Pool",
  "balance_usd": 150.0,
  ...
}

🧪 Routing Demo:
────────────────────────────────────────
  Prompt: What is the capital of France?
  → [ROUTED TO Team Beta (Budget)] Model: claude-3-haiku | Cost estimate: $0.000184

  Prompt: Write a Python function to sort a list
  → [ROUTED TO Local Ollama (Free)] Model: codellama-7b | Cost estimate: $0.000000
```

### Building the Plugin

```bash
cd client-side/zed-plugin
cargo build --release
cp target/release/llm-gateway-plugin.dll %APPDATA%\zed\plugins\
```

### Running the Server (optional)

```bash
cd server-side
python run.py --host 0.0.0.0 --port 8080
```

---

## Next Steps / Future Work

- [ ] Add Redis backend for distributed deployments
- [ ] Add WebSocket support for real-time cost dashboards
- [ ] Add per-user budget sharing (family/team plans)
- [ ] Add model fine-tuning routing (route specific tasks to fine-tuned models)
- [ ] Add rate-limiting with exponential backoff
- [ ] Add telemetry/analytics export

---

## License

MIT — see [LICENSE](../LICENSE)
