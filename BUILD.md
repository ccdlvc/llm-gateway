# Building the LLM Gateway Zed Plugin

## Prerequisites

- **Python 3.9+** (for the server-side)
- **Rust toolchain** (for the Zed plugin): `rustup install stable`
- **Zed editor** (version 0.145+)

---

## Step 1: Build the Server-Side

```bash
cd server-side
pip install -r requirements.txt

# Verify it works
python cli.py help
python cli.py pool-status
```

## Step 2: Build the Zed Plugin

```bash
cd client-side/zed-plugin

# Install Rust toolchain
rustup install stable

# Build in release mode for better performance
cargo build --release

# The plugin binary will be at:
# Windows: target/release/llm-gateway-plugin.dll
# Linux/macOS: target/release/libllm_gateway_plugin.so
```

## Step 3: Install in Zed

### Windows

1. Open Zed settings (`Ctrl+,`)
2. Go to **Settings → Plugins**
3. Click **"Install from path"** or copy the DLL to:
   ```
   %APPDATA%\zed\plugins\llm-gateway.dll
   ```

### Linux/macOS

```bash
mkdir -p ~/.local/share/zed/plugins
cp target/release/libllm_gateway_plugin.so ~/.local/share/zed/plugins/
```

## Step 4: Configure in Zed

Edit your Zed settings (`~/.config/zed/settings.json` or `Cmd/Ctrl+, → Settings`):

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

## Step 5: Run the Gateway Server

```bash
cd server-side
python run.py --host 0.0.0.0 --port 8080
```

Or use the Makefile:

```bash
make start
```

## Step 6: Add Accounts (CLI)

```bash
python cli.py add-account \
  --name "Team Alpha" \
  --api-key "sk-ant-your-api-key-here" \
  --balance 100 \
  --weight 2.0
```

## Verification

After restarting Zed, you should see:

1. The plugin appears in the **Command Palette** (`Cmd/Ctrl+Shift+P`)
2. A panel showing your virtual pool balance
3. Cost tracking on each response

---

## Troubleshooting

### Plugin not loading?

- Verify the DLL/SO file is in the correct plugins directory
- Restart Zed completely
- Check Zed's log for plugin errors

### Can't connect to gateway?

- Ensure the server is running: `python run.py`
- Check that port 8080 is not blocked by a firewall
- Verify your network allows access to localhost:8080

### "No healthy accounts" error?

Run:
```bash
python cli.py show-accounts
```

If no accounts are listed, add one:
```bash
python cli.py add-account --name "Test" --api-key "sk-test" --balance 1
```

---

## Development Workflow

### Hot-reloading the plugin

For development, you can rebuild without a full Zed restart:

```bash
cd client-side/zed-plugin
cargo build
# Copy to plugins directory (Windows)
copy target\release\llm-gateway-plugin.dll "%APPDATA%\zed\plugins\\"
# Or (Linux/macOS)
cp target/release/libllm_gateway_plugin.so ~/.local/share/zed/plugins/
```

### Running the demo without Zed

```bash
cd client-side/zed-plugin
python demo.py
```

This shows the routing engine in action with mock responses.

---

## License

MIT — see [LICENSE](../LICENSE)
