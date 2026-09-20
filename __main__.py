#!/usr/bin/env python3
"""Entry point for `python -m llm_gateway`."""

import sys
import os

# Determine which module to run based on the subcommand
if len(sys.argv) < 2:
    print("Usage: python -m llm_gateway <command>")
    print("Commands:")
    print("  proxy [--host HOST] [--port PORT]  Start the proxy server")
    print("  cli <subcommand>                    Run CLI commands")
    sys.exit(1)

command = sys.argv[1]

if command == "proxy":
    os.chdir(os.path.join(os.path.dirname(__file__), "server-side"))
    from run import main
    main()

elif command == "cli":
    os.chdir(os.path.join(os.path.dirname(__file__), "server-side"))
    from cli import main
    main()

else:
    print(f"Unknown command: {command}")
    sys.exit(1)
