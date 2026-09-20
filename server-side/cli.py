#!/usr/bin/env python3
"""
LLM Gateway CLI - Command-line interface for managing accounts and budgets.

Usage:
    llm-gateway cli add-account --name "My Account" --api-key "sk-..." --balance 50
    llm-gateway cli set-budget --account-id acc-x --limit 10.0
    llm-gateway cli pool-status
    llm-gateway cli remove-account --id acc-x
"""

import argparse
import json
import sys
import os
from datetime import datetime
from dataclasses import asdict
from typing import Optional

# Add server-side to path
sys.path.insert(0, str(__file__[:-1]))

from gateway import LLMGateway, AccountConfig, AccountStatus


def get_gateway() -> LLMGateway:
    """Get or create the gateway instance (singleton)."""
    db_path = os.path.join(os.path.dirname(__file__), "gateway.db")
    if not os.path.exists(db_path):
        return LLMGateway()
    
    # Load existing accounts from DB
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM accounts")
    rows = cursor.fetchall()
    conn.close()
    
    gateway = LLMGateway(db_path=db_path)
    for row in rows:
        config = AccountConfig(
            id=row[0], name=row[1], api_key_hash=row[2],
            base_url=row[3] or "https://api.anthropic.com",
            model=row[4] or "claude-3-5-sonnet-20241022",
            max_tokens=row[5] or 8192,
            weight=float(row[6]), enabled=bool(row[7]),
            status=AccountStatus(row[8]),
            remaining_balance=row[9], tokens_used=row[10],
            total_cost_usd=row[11],
        )
        gateway.register_account(config)
    
    return gateway


def cmd_add_account(args: argparse.Namespace) -> None:
    """Add a new account."""
    gateway = get_gateway()
    
    config = AccountConfig(
        id=f"acc-{int(datetime.utcnow().timestamp() * 1000)}",
        name=args.name,
        api_key=args.api_key,
        base_url=args.base_url or "https://api.anthropic.com",
        model=args.model or "claude-3-5-sonnet-20241022",
        max_tokens=int(args.max_tokens) if args.max_tokens else 8192,
        weight=float(args.weight) if args.weight else 1.0,
        enabled=True,
        status=AccountStatus.HEALTHY,
        remaining_balance=float(args.balance) if args.balance else 0.0,
    )
    
    account_id = gateway.register_account(config)
    print(f"✓ Account added: {config.name} (id={account_id})")
    print(f"  Model: {config.model}")
    print(f"  Balance: ${config.remaining_balance:.2f}")
    print(f"  Weight: {config.weight}")


def cmd_remove_account(args: argparse.Namespace) -> None:
    """Remove an account."""
    gateway = get_gateway()
    gateway.unregister_account(args.id)
    print(f"✓ Account removed: {args.id}")


def cmd_set_budget(args: argparse.Namespace) -> None:
    """Set a budget limit for an account."""
    gateway = get_gateway()
    
    if args.account_id not in gateway.router.accounts:
        print(f"✗ Account '{args.account_id}' not found.")
        return
    
    acc = gateway.router.accounts[args.account_id]
    acc.budget_limit = float(args.limit)
    
    print(f"✓ Budget set for '{acc.name}': ${args.limit:.2f}")
    print(f"  Warning threshold: {args.warning_threshold}%")


def cmd_pool_status(args: argparse.Namespace) -> None:
    """Show the virtual pool status."""
    gateway = get_gateway()
    pool = gateway.get_virtual_pool()
    
    print(json.dumps(pool, indent=2))


def cmd_show_accounts(args: argparse.Namespace) -> None:
    """List all registered accounts."""
    gateway = get_gateway()
    
    print("Registered Accounts:")
    print("-" * 60)
    for acc in gateway.router.accounts.values():
        if acc.enabled:
            cost = gateway.cost_trackers.get(acc.id, 0.0)
            print(f"  {acc.name:<30} | ${acc.remaining_balance:>8.2f} | "
                  f"${cost:>6.4f} spent")


def cmd_help(args: argparse.Namespace) -> None:
    """Show help message."""
    help_text = """LLM Gateway CLI

Usage:
  llm-gateway cli add-account --name "Name" --api-key "sk-..." --balance 50
  llm-gateway cli remove-account --id acc-x
  llm-gateway cli set-budget --account-id acc-x --limit 10.0
  llm-gateway cli pool-status
  llm-gateway cli show-accounts
  llm-gateway cli help

Environment Variables:
  GATEWAY_DB_PATH   Path to the SQLite database (default: ./gateway.db)
"""
    print(help_text)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="llm-gateway",
        description="LLM Gateway - Balance-aware routing for multi-account Claude usage"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # add-account
    p_add = subparsers.add_parser("add-account", help="Add a new account")
    p_add.add_argument("--name", required=True, help="Account name")
    p_add.add_argument("--api-key", required=True, help="API key (stored hashed)")
    p_add.add_argument("--balance", type=float, default=0.0, help="Starting balance")
    p_add.add_argument("--model", default="claude-3-5-sonnet-20241022", help="Model to use")
    p_add.add_argument("--weight", type=float, default=1.0, help="Routing weight")
    p_add.add_argument("--base-url", help="Custom API endpoint")
    
    # remove-account
    p_remove = subparsers.add_parser("remove-account", help="Remove an account")
    p_remove.add_argument("--id", required=True, help="Account ID to remove")
    
    # set-budget
    p_budget = subparsers.add_parser("set-budget", help="Set a budget limit")
    p_budget.add_argument("--account-id", required=True, help="Account ID")
    p_budget.add_argument("--limit", type=float, required=True, help="Budget limit in USD")
    p_budget.add_argument("--warning-threshold", type=float, default=80.0,
                          help="Warning threshold percentage")
    
    # pool-status
    subparsers.add_parser("pool-status", help="Show virtual pool status")
    
    # show-accounts
    subparsers.add_parser("show-accounts", help="List all accounts")
    
    # help
    subparsers.add_parser("help", help="Show this help message")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == "add-account":
        cmd_add_account(args)
    elif args.command == "remove-account":
        cmd_remove_account(args)
    elif args.command == "set-budget":
        cmd_set_budget(args)
    elif args.command == "pool-status":
        cmd_pool_status(args)
    elif args.command == "show-accounts":
        cmd_show_accounts(args)
    elif args.command == "help":
        cmd_help(args)


if __name__ == "__main__":
    main()
