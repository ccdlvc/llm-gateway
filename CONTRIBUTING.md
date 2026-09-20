# Contributing to LLM Gateway

## Getting Started

1. Fork and clone this repository
2. Read [BUILD.md](BUILD.md) for setup instructions
3. Run the demo: `python client-side/zed-plugin/demo.py`

## Development Workflow

### Adding a New Model

Edit `server-side/cost_optimizer.py`:

```python
MODEL_COSTS["codellama-7b"] = ModelCostProfile(
    model_name="codellama-7b",
    cost_per_token_input=0.0,      # $0 for local
    cost_per_token_output=0.0,
    context_window=4_096,
    typical_response_length=200,
)
```

Add a route in `multi_model_gateway.py`:

```python
task_model_map = {
    "code_generation": "codellama",  # Your new model
    ...
}
```

### Adding a New Account via CLI

```bash
python cli.py add-account \
  --name "My Account" \
  --api-key "sk-..." \
  --balance 50 \
  --model "claude-3-5-sonnet"
```

### Modifying the Plugin

1. Edit `client-side/zed-plugin/src/lib.rs` or `src/main.rs`
2. Build: `cargo build --release`
3. Copy to Zed's plugins directory
4. Restart Zed

## Code Style

- **Python**: Follow [PEP 8](https://pep8.org/)
- **Rust**: Follow the Rust style guide; `cargo fmt` enforces it

## Testing

```bash
cd server-side
python -m pytest tests/

# Or run the demo interactively
cd client-side/zed-plugin
python demo.py
```

## Code of Conduct

Be respectful and inclusive. We value diverse contributions.

## License

By contributing, you agree that your contributions will be licensed under the MIT license.
