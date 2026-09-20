# LLM Gateway - Zed Plugin

A Zed plugin that provides **balance-aware routing** across multiple LLM accounts with cost optimization and budget management.

## ✨ Features

- **Multi-account pooling** — Aggregate balances across multiple Claude/Codex/Ollama accounts
- **Automatic failover** — Switch to backup accounts when primary is rate-limited or exhausted
- **Cost optimization** — Route simple queries to cheaper models (Haiku, Codex, Ollama)
- **Budget limits** — Per-account spending limits with warnings and hard stops
- **Virtual pool** — Unified balance view across all accounts
- **Sticky sessions** — Keep conversation context within one account

## 🚀 Quick Start

### Step 1: Build the Plugin

```bash
cd client-side/zed-plugin
cargo build --release
```

This produces `target/release/llm-gateway-plugin` (the `.dll` on Windows).

### Step 2: Install in Zed

1. Open Zed settings (`Cmd+,` on macOS / `Ctrl+,` on Windows)
2. Go to **Settings → Plugins**
3. Click **"Install from path"** or copy the built plugin to:
   - Windows: `%APPDATA%\zed\plugins\`
   - Linux/macOS: `~/.local/share/zed/plugins/`

### Step 3: Configure Your Accounts

Edit your Zed settings.json (or use the plugin UI):

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

### Step 4: Run the Gateway Server

```bash
cd ../server-side
python -m llm_gateway proxy --host 0.0.0.0 --port 8080
```

Or use the CLI:

```bash
llm-gateway cli add-account \
  --name "Team Alpha" \
  --api-key "sk-ant-..." \
  --balance 100 \
  --weight 2.0
```

## 📖 Usage

### Adding Accounts

```bash
llm-gateway cli add-account \
  --name "My Personal Account" \
  --api-key "sk-ant-xxxxxx" \
  --balance 50 \
  --model "claude-3-5-sonnet"
```

### Setting Budget Limits

```bash
llm-gateway cli set-budget \
  --account-id "acc-xxx" \
  --limit 10.0 \
  --warning-threshold 80
```

### Viewing Pool Status

Open the plugin's UI panel in Zed to see:
- Virtual pool balance
- Per-account balances
- Cost tracking per session
- Routing decisions

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Zed Plugin                             │
│  ┌─────────────────┬─────────────────┬─────────────────┐ │
│  │  Account Router │   Cost Optimizer│    Budget UI     │ │
│  │                  │                 │                  │ │
│  │  • Balance      │  • Task-type    │  • Add/Remove    │ │
│  │    aware         │    routing     │    Accounts       │ │
│  │  • Sticky        │  • Budget      │  • Set Limits     │ │
│  │    sessions      │    enforcement  │  • View Pool      │ │
│  └─────────────────┴─────────────────┴──────────────────┘ │
│                           │                                │
│  ┌───────────────────────▼─────────────────────────────┐ │
│  │              LLM Client Hook                         │ │
│  │  Intercepts requests from Zed's LLM client           │ │
│  └─────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘

                    ▼
          ┌──────────────────────────┐
          │   Gateway Server         │
          │   (Flask/asyncio)        │
          │                          │
          │  • Account registration  │
          │  • Request routing       │
          │  • Cost tracking         │
          │  • Audit logging         │
          └──────────────────────────┘
```

## 🔧 Development

### Building

```bash
cd client-side/zed-plugin
cargo build --release
cp target/release/llm-gateway-plugin ~/.local/share/zed/plugins/
```

### Running Tests

```bash
cargo test
```

### Running the Demo (no Rust needed)

```bash
python demo.py
```

## 📦 Project Structure

```
llm-gateway/
├── server-side/              # Core gateway logic (language-agnostic)
│   ├── gateway.py           # Main routing engine
│   ├── cost_optimizer.py    # Cost-aware routing
│   ├── multi_model_gateway.py # Multi-model support
│   └── cli.py               # Command-line interface
├── client-side/
│   └── zed-plugin/          # Zed plugin (Rust)
│       ├── Cargo.toml
│       ├── src/
│       │   ├── lib.rs      # Core gateway logic (Rust port)
│       │   ├── main.rs     # Plugin entry point
│       │   └── gateway.rs  # Shared types
│       ├── zed_plugin.toml
│       └── demo.py         # Python demo
└── README.md
```

## 📝 License

MIT License — see [LICENSE](../LICENSE)
