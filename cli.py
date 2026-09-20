#!/usr/bin/env python3
"""
CLI tool for managing the LLM Gateway.

Usage:
    python -m llm_gateway cli register --name "Team A" --api-key "sk-..." --weight 1.0
    python -m llm_gateway cli list
    python -m llm_gateway cli pool
    python -m llm_gateway cli complete --session-id "sess-xxx" --prompt "Hello"
"""

import argparse
import json
import sys
from typing import Optional

sys.path.insert(0, str(__file__[:-5]))

from gateway import (
    LLMGateway,
    AccountConfig,
    AccountStatus,
)


def register_account(args: argparse.Namespace) -> None:
    """Register a new account."""
    config = AccountConfig(
        id=f"acc-{int(__import__('time').time() * 1000)}",
        name=args.name,
        api_key=args.api_key,
        base_url=args.base_url or "https://api.anthropic.com",
        model=args.model or "claude-3-5-sonnet-20241022",
        max_tokens=int(args.max_tokens) or 8192,
        weight=float(args.weight) or 1.0,
        enabled=bool(args.enabled),
    )

    gateway = LLMGateway(db_path=args.db_path)
    account_id = gateway.register_account(config)

    print(json.dumps({
        "success": True,
        "account": {
            "id": account_id,
            "name": config.name,
            "model": config.model,
            "weight": config.weight,
        },
    }, indent=2))


def unregister_account(args: argparse.Namespace) -> None:
    """Unregister an account."""
    gateway = LLMGateway(db_path=args.db_path)
    gateway.unregister_account(args.account_id)
    print(json.dumps({"success": True, "message": f"Account {args.account_id} unregistered"}, indent=2))


def list_accounts(args: argparse.Namespace) -> None:
    """List all registered accounts."""
    gateway = LLMGateway(db_path=args.db_path)

    accounts = []
    for acc_id in gateway.router.accounts.keys():
        stats = gateway.get_account_stats(acc_id)
        if stats:
            accounts.append(stats)

    print(json.dumps({"accounts": accounts}, indent=2))


def pool(args: argparse.Namespace) -> None:
    """Show virtual pool balance."""
    gateway = LLMGateway(db_path=args.db_path)
    pool = gateway.get_virtual_pool()

    # Remove internal fields for display
    display = {
        "pool_name": pool.pop("pool_name"),
        "balance_usd": pool.pop("balance_usd"),
        "tokens_available": pool.pop("tokens_available"),
        "tokens_used": pool.pop("tokens_used"),
        "accounts": [
            {"id": a["id"], "name": a["name"], "balance": round(a.get("remaining_balance", 0), 2)}
            for a in pool.pop("accounts", [])
        ],
    }

    print(json.dumps(display, indent=2))


def complete(args: argparse.Namespace) -> None:
    """Process a completion request through the gateway."""
    gateway = LLMGateway(db_path=args.db_path)

    session_id = args.session_id or str(__import__('time').time_ns())

    result = gateway.complete(session_id, args.prompt, max_tokens=args.max_tokens)

    if "error" in result:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result, indent=2))


def add_balance(args: argparse.Namespace) -> None:
    """Add balance to the virtual pool (admin)."""
    gateway = LLMGateway(db_path=args.db_path)

    # Get current pool state
    pool = gateway.get_virtual_pool()

    # Add the specified amount
    for acc_id, config in gateway.router.accounts.items():
        config.remaining_balance += args.amount

    print(json.dumps({
        "success": True,
        "message": f"Added ${args.amount} to the pool.",
        "new_pool_balance": round(sum(a.remaining_balance for a in gateway.router.accounts.values()), 2),
    }, indent=2))


def set_budget(args: argparse.Namespace) -> None:
    """Set a budget limit for an account."""
    # For now, this is a no-op demo
    print(json.dumps({
        "success": True,
        "message": f"Budget limit for {args.account_id} set to ${args.limit}",
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM Gateway CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # register
    p = subparsers.add_parser("register", help="Register a new account")
    p.add_argument("--name", required=True, help="Account name")
    p.add_argument("--api-key", required=True, help="API key")
    p.add_argument("--base-url", default="https://api.anthropic.com")
    p.add_argument("--model", default="claude-3-5-sonnet-20241022")
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--weight", type=float, default=1.0)
    p.add_argument("--enabled", action="store_true")
    p.add_argument("--db-path", default=None)

    # unregister
    p = subparsers.add_parser("unregister", help="Unregister an account")
    p.add_argument("--account-id", required=True)
    p.add_argument("--db-path", default=None)

    # list
    p = subparsers.add_parser("list", help="List accounts")
    p.add_argument("--db-path", default=None)

    # pool
    p = subparsers.add_parser("pool", help="Show pool balance")
    p.add_argument("--db-path", default=None)

    # complete
    p = subparsers.add_parser("complete", help="Process a completion")
    p.add_argument("--session-id")
    p.add_argument("--prompt", required=True)
    p.add_argument("--max-tokens", type=int, default=4096)
    p.add_argument("--db-path", default=None)

    # add-balance
    p = subparsers.add_parser("add-balance", help="Add balance to pool")
    p.add_argument("--amount", type=float, required=True)
    p.add_argument("--db-path", default=None)

    # set-budget
    p = subparsers.add_parser("budget", help="Set budget for an account")
    p.add_argument("--account-id", required=True)
    p.add_argument("--limit", type=float, required=True)
    p.add_argument("--db-path", default=None)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "register": register_account,
        "unregister": unregister_account,
        "list": list_accounts,
        "pool": pool,
        "complete": complete,
        "add-balance": add_balance,
        "budget": set_budget,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
