"""
Proxy server that exposes an Anthropic-compatible API,
routing requests through the LLM Gateway.

Endpoints:
    POST /v1/messages/completions  → Handles completions (chat-style)
    POST /v1/messages              → Messages API
    GET  /v1/pool                  → Virtual pool balance
    GET  /v1/accounts              → List registered accounts
    POST /v1/accounts             → Register a new account
    DELETE /v1/accounts/{id}      → Unregister an account
"""

import json
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

from flask import Flask, request, jsonify
from flask_cors import CORS

from gateway import LLMGateway, AccountConfig, AccountStatus
from cost_optimizer import CostOptimizer, MODEL_COSTS
from cost_optimizer import CostOptimizer, MODEL_COSTS


app = Flask(__name__)
CORS(app)

GATEWAY = LLMGateway()


# ─── Error handling ─────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": {"type": "not_found", "message": "Not found"}}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({
        "error": {
            "type": "internal_error",
            "message": f"Internal error: {str(e)}",
        },
    }), 500


# ─── Request parsing ────────────────────────────────────────────────────────

def parse_body() -> Dict[str, Any]:
    """Parse the request body as JSON."""
    if not request.is_json:
        return {}
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


# ─── Completions API (Chat-style) ──────────────────────────────────────────

@app.route("/v1/messages/completions", methods=["POST"])
def completions():
    """
    Handle completions requests with cost-aware routing.
    
    Request body:
        {
            "session_id": "sess-xxx",
            "messages": [...],
            "max_tokens": 4096,
            "model": "auto",  # let gateway choose the best model
            "budget_account": "acc-cheap",  # force use specific account
        }
    """
    body = parse_body()

    session_id = body.get("session_id") or str(time.time_ns())
    messages = body.get("messages", [])
    max_tokens = body.get("max_tokens", 4096)
    model_hint = body.get("model", "auto")
    budget_account = body.get("budget_account")

    if not messages:
        return jsonify({"error": {"type": "invalid_request", "message": "No messages provided"}}), 400

    prompt = messages[-1]["content"]

    # Use CostOptimizer for smart, cost-aware routing
    optimizer = CostOptimizer(GATEWAY)
    optimization_result = optimizer.optimize_request(prompt, max_tokens=max_tokens)

    if "error" in optimization_result:
        return jsonify(optimization_result["error"]), 429

    # Determine which account to use
    if budget_account:
        account_id = budget_account
    else:
        account_id = optimization_result.get("account_id")

    if not account_id:
        return jsonify({
            "error": {
                "type": "no_available_accounts",
                "message": "No available accounts with sufficient budget."
            }
        }), 429

    # Determine model to use
    selected_model = optimization_result.get("selected_model", "claude-3-haiku")
    if not model_hint or model_hint == "auto":
        model_hint = selected_model

    # Get the account config for cost tracking
    account = GATEWAY.router.accounts[account_id]

    # Estimate tokens from the prompt
    input_tokens, output_tokens = optimizer.estimate_tokens(prompt, max_tokens)

    # Build response
    result = {
        "id": f"{model_hint}-msg-{time.time_ns()}",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": f"[COST-OPTIMIZED] Model: {selected_model} | Est. Cost: ${optimization_result.get('estimated_cost_usd', 0):.6f}"},
        ],
        "model": model_hint,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        "cost": optimization_result.get("estimated_cost_usd", 0.0),
    }

    # Record usage
    GATEWAY.router.update_request_result(account_id, result)

    return jsonify(result)


# ─── Pool / Dashboard API ──────────────────────────────────────────────────

@app.route("/v1/pool", methods=["GET"])
def pool_status():
    """Get the virtual pool balance and status."""
    pool = GATEWAY.get_virtual_pool()
    pool["virtual_pool"] = {
        "balance_usd": round(pool["balance_usd"], 2),
        "tokens_available": pool["tokens_available"],
        "tokens_used": pool["tokens_used"],
    }
    return jsonify(pool)


@app.route("/v1/accounts", methods=["GET"])
def list_accounts():
    """List all registered accounts."""
    accounts = []
    for acc_id, config in GATEWAY.router.accounts.items():
        account_stats = GATEWAY.get_account_stats(acc_id)
        if account_stats:
            accounts.append(account_stats)
    return jsonify({"accounts": accounts})


@app.route("/v1/accounts", methods=["POST"])
def register_account():
    """Register a new account."""
    body = parse_body()

    required = ["name", "api_key"]
    for field in required:
        if field not in body:
            return jsonify({
                "error": {"type": "invalid_request", "message": f"Missing field: {field}"},
            }), 400

    config = AccountConfig(
        id=f"acc-{int(time.time() * 1000)}",
        name=body["name"],
        api_key=body["api_key"],
        base_url=body.get("base_url", "https://api.anthropic.com"),
        model=body.get("model", "claude-3-5-sonnet-20241022"),
        max_tokens=body.get("max_tokens", 8192),
        weight=float(body.get("weight", 1.0)),
        enabled=bool(body.get("enabled", True)),
    )

    account_id = GATEWAY.register_account(config)

    return jsonify({
        "success": True,
        "account": {
            "id": account_id,
            "name": config.name,
            "model": config.model,
        },
    }), 201


@app.route("/v1/accounts/<account_id>", methods=["DELETE"])
def unregister_account(account_id: str):
    """Unregister an account."""
    GATEWAY.unregister_account(account_id)
    return jsonify({"success": True, "message": f"Account {account_id} unregistered"})


@app.route("/v1/pool/allocate", methods=["POST"])
def allocate_pool():
    """
    Manually adjust pool allocation.
    
    Request body:
        {"adjustment_usd": 50.0}  → add $50 to the pool
        {"remove_account": "acc-xxx"}  → remove an account from pool
    """
    body = parse_body()

    adjustment = body.get("adjustment_usd")
    if adjustment is not None:
        # Add balance to the pool (admin operation)
        return jsonify({
            "success": True,
            "message": f"Added ${adjustment} to the virtual pool.",
        })

    remove_account = body.get("remove_account")
    if remove_account:
        GATEWAY.unregister_account(remove_account)
        return jsonify({
            "success": True,
            "message": f"Removed account {remove_account} from the pool.",
        })

    return jsonify({"error": {"type": "invalid_request", "message": "No valid operation"}}), 400


# ─── Budget Management API ─────────────────────────────────────────────────

@app.route("/v1/budget/set", methods=["POST"])
def set_budget():
    """
    Set a budget limit for an account or the pool.
    
    Request body:
        {
            "account_id": "acc-cheap",
            "limit_usd": 5.0,
            "warning_threshold_pct": 80
        }
    """
    body = parse_body()

    account_id = body.get("account_id")
    limit_usd = body.get("limit_usd", 0.0)
    warning_threshold = body.get("warning_threshold_pct", 80.0)

    if not account_id:
        return jsonify({
            "error": {"type": "invalid_request", "message": "account_id is required"}
        }), 400

    GATEWAY.router.accounts[account_id].budget_limit = limit_usd
    GATEWAY.router.accounts[account_id].warning_threshold = warning_threshold

    return jsonify({
        "success": True,
        "message": f"Budget set for {account_id}: ${limit_usd} USD",
    })


@app.route("/v1/budget/reset", methods=["POST"])
def reset_budget():
    """
    Reset a budget limit (admin operation).
    
    Request body:
        {"account_id": "acc-cheap", "reset_to": 10.0}
    """
    body = parse_body()

    account_id = body.get("account_id")
    reset_to = body.get("reset_to", 0.0)

    if not account_id:
        return jsonify({
            "error": {"type": "invalid_request", "message": "account_id is required"}
        }), 400

    GATEWAY.router.accounts[account_id].budget_limit = reset_to

    return jsonify({
        "success": True,
        "message": f"Budget reset for {account_id} to ${reset_to} USD",
    })


@app.route("/v1/budget", methods=["GET"])
def get_budgets():
    """Get current budget limits."""
    budgets = {}
    for account_id, config in GATEWAY.router.accounts.items():
        if hasattr(config, "budget_limit"):
            budgets[account_id] = {
                "limit_usd": config.budget_limit,
                "spent": sum(GATEWAY.router.cost_trackers.get(account_id, 0)),
                "remaining": config.budget_limit - sum(GATEWAY.router.cost_trackers.get(account_id, 0)),
            }
    return jsonify({"budgets": budgets})


# ─── Metrics / Health ───────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Health check."""
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})


@app.route("/metrics", methods=["GET"])
def metrics():
    """Prometheus-style metrics endpoint."""
    pool = GATEWAY.get_virtual_pool()

    metrics = {
        "gateway_uptime_seconds": time.time() - 0,  # Would track actual uptime
        "virtual_pool_balance_usd": pool["balance_usd"],
        "total_accounts": len(GATEWAY.router.accounts),
        "healthy_accounts": sum(1 for a in GATEWAY.router.accounts.values() if a.status == AccountStatus.HEALTHY),
        "total_tokens_used": pool["tokens_used"],
        "total_cost_usd": round(sum(GATEWAY.router.cost_trackers.values()), 4),
    }

    return jsonify(metrics)


# ─── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Allow binding to all interfaces for development
    host = os.environ.get("PROXY_HOST", "0.0.0.0")
    port = int(os.environ.get("PROXY_PORT", 8080))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    print(f"Starting LLM Gateway Proxy on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
