#!/usr/bin/env python3
"""
LLM Gateway - Standalone Server

Run this to start the proxy server that Claude Code will connect to.

Usage:
    python run.py --host 0.0.0.0 --port 8080
"""

import argparse
import os
import sys
import json
from typing import Any, Optional

# Add server-side to path
sys.path.insert(0, str(__file__[:-1]))

from gateway import LLMGateway, AccountConfig, AccountStatus


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="llm-gateway",
        description="LLM Gateway - Balance-aware routing proxy"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=8080, help="Port")
    parser.add_argument("--db", help="Path to SQLite database")
    args = parser.parse_args()

    # Import here to avoid circular imports with Flask
    from flask import Flask, request, jsonify
    from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)

    gateway = LLMGateway(db_path=args.db)

    # ─── Health check ────────────────────────────────────────────────────────
    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "healthy", "gateway": "llm-gateway"})

    # ─── Account Management ──────────────────────────────────────────────────
    @app.route("/v1/accounts", methods=["POST"])
    def register_account():
        body = request.get_json() or {}

        config = AccountConfig(
            id=f"acc-{int(__import__('time').time() * 1000)}",
            name=body["name"],
            api_key=body["api_key"],
            base_url=body.get("base_url", "https://api.anthropic.com"),
            model=body.get("model", "claude-3-5-sonnet-20241022"),
            max_tokens=int(body.get("max_tokens", 8192)),
            weight=float(body.get("weight", 1.0)),
            enabled=bool(body.get("enabled", True)),
            remaining_balance=float(body.get("balance", 0.0)),
        )

        gateway.register_account(config)
        return jsonify({
            "success": True,
            "account_id": config.id,
            "name": config.name,
        })

    @app.route("/v1/accounts/<account_id>", methods=["DELETE"])
    def unregister_account(account_id: str):
        gateway.unregister_account(account_id)
        return jsonify({"success": True, "message": f"Account {account_id} removed"})

    # ─── Completions API (Anthropic-compatible) ──────────────────────────────
    @app.route("/v1/messages/completions", methods=["POST"])
    def completions():
        body = request.get_json() or {}

        session_id = body.get("session_id") or str(__import__('time').time_ns())
        messages = body.get("messages", [])
        max_tokens = int(body.get("max_tokens", 4096))

        if not messages:
            return jsonify({
                "error": {"type": "invalid_request", "message": "No messages provided"}
            }), 400

        prompt = messages[-1].get("content", "")

        result = gateway.complete(session_id, prompt, max_tokens=max_tokens)

        if "error" in result:
            return jsonify(result["error"]), 429

        return jsonify(result)

    # ─── Pool Status ─────────────────────────────────────────────────────────
    @app.route("/v1/pool", methods=["GET"])
    def pool_status():
        pool = gateway.get_virtual_pool()
        pool["virtual_pool"] = {
            "balance_usd": round(pool["balance_usd"], 2),
            "tokens_available": pool["tokens_available"],
        }
        return jsonify(pool)

    # ─── Account Stats ───────────────────────────────────────────────────────
    @app.route("/v1/accounts/<account_id>", methods=["GET"])
    def get_account_stats(account_id: str):
        stats = gateway.get_account_stats(account_id)
        if stats:
            return jsonify(stats)
        return jsonify({"error": {"type": "not_found", "message": f"Account {account_id} not found"}}), 404

    # ─── Budget Management ───────────────────────────────────────────────────
    @app.route("/v1/budget/set", methods=["POST"])
    def set_budget():
        body = request.get_json() or {}
        account_id = body.get("account_id")
        limit_usd = float(body.get("limit_usd", 0.0))

        if not account_id:
            return jsonify({"error": "account_id is required"})), 400

        acc = gateway.router.accounts[account_id]
        acc.budget_limit = limit_usd
        return jsonify({
            "success": True,
            "message": f"Budget set for {account_id}: ${limit_usd:.2f}",
        })

    # ─── Start server ────────────────────────────────────────────────────────
    host = args.host
    port = args.port

    print(f"Starting LLM Gateway on http://{host}:{port}")
    print("Endpoints:")
    print(f"  POST   /v1/messages/completions  → Route completions")
    print(f"  GET    /v1/pool                   → Pool balance")
    print(f"  POST   /v1/accounts              → Register account")
    print(f"  DELETE /v1/accounts/<id>         → Remove account")
    print(f"  GET    /v1/accounts/<id>         → Account stats")
    print(f"  POST   /v1/budget/set            → Set budget limit")
    print(f"  GET    /health                    → Health check")
    print()

    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
