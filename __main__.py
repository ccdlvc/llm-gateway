#!/usr/bin/env python3
"""CLI entry point for llm-gateway."""

import argparse
import sys
from pathlib import Path

# Add the package directory to path
this_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(this_dir))


def main():
    """Entry point for `llm-gateway` command."""
    parser = argparse.ArgumentParser(
        prog="llm-gateway",
        description="LLM Gateway — Balance-aware routing for multi-account LLM usage.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # proxy server
    p = subparsers.add_parser("proxy", help="Start the HTTP proxy server")
    p.add_argument("--host", default="0.0.0.0", help="Bind address")
    p.add_argument("--port", type=int, default=8080, help="Port")
    p.add_argument("--debug", action="store_true", help="Enable debug mode")

    # CLI commands
    p = subparsers.add_parser("cli", help="CLI subcommands")
    sub = p.add_subparsers(dest="subcommand")

    # register
    r = sub.add_parser("register", help="Register an account")
    r.add_argument("--name", required=True, help="Account name")
    r.add_argument("--api-key", required=True, help="API key")
    r.add_argument("--weight", type=float, default=1.0, help="Routing weight")
    r.add_argument("--balance", type=float, default=0.0, help="Initial balance ($)")

    # list
    sub.add_parser("list", help="List registered accounts")

    # pool
    sub.add_parser("pool", help="Show virtual pool status")

    # demo
    sub.add_parser("demo", help="Run interactive demo")

    args = parser.parse_args()

    if args.command == "proxy":
        from proxy import app
        from flask import Flask

        app.run(host=args.host, port=args.port, debug=args.debug)

    elif args.command == "cli":
        from cli import main as cli_main
        cli_main()

    elif args.command == "demo":
        from run_demo import main as demo_main
        demo_main()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
