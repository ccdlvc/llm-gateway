#!/usr/bin/env python3
"""
Demo script demonstrating the LLM Gateway's balance-aware routing.

Run:
    python -m llm_gateway demo
"""

import json
import time
import sys
from datetime import timedelta

sys.path.insert(0, str(__file__[:-5]))

from gateway import (
    LLMGateway,
    AccountConfig,
    AccountStatus,
)


def demo_basic_routing():
    """Demonstrate basic balance-aware routing."""
    print("=" * 60)
    print("DEMO: Balance-Aware Routing")
    print("=" * 60)

    gateway = LLMGateway()

    # Register accounts with different balances
    accounts = [
        AccountConfig(
            id="acc-1",
            name="Team Alpha - Claude 3.5 Sonnet",
            api_key="sk-test-alpha-key",
            weight=1.0,
            remaining_balance=100.0,  # $100 = ~6.7B tokens
        ),
        AccountConfig(
            id="acc-2",
            name="Team Beta - Claude 3.5 Sonnet",
            api_key="sk-test-beta-key",
            weight=1.0,
            remaining_balance=40.0,   # $40 = ~2.7B tokens
        ),
        AccountConfig(
            id="acc-3",
            name="Team Gamma - Claude 3.5 Sonnet",
            api_key="sk-test-gamma-key",
            weight=1.0,
            remaining_balance=160.0,  # $160 = ~10.7B tokens
        ),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    # Start a session
    session_id = "sess-demo-1"
    gateway.start_session(session_id)

    print("\n--- Initial Pool State ---")
    pool = gateway.get_virtual_pool()
    print(json.dumps(pool, indent=2))

    # Simulate multiple requests
    print("\n--- Routing Decisions ---")
    for i in range(5):
        prompt = f"Explain concept {i+1} of quantum computing."
        result = gateway.complete(session_id, prompt)
        print(f"  Request {i+1}: routed to {result['model']} (cost: ${result.get('cost', 0):.6f})")

    print("\n--- Updated Pool ---")
    pool = gateway.get_virtual_pool()
    print(json.dumps(pool, indent=2))


def demo_weighted_routing():
    """Demonstrate weighted routing."""
    print("\n" + "=" * 60)
    print("DEMO: Weighted Routing (Team Gamma has weight=3.0)")
    print("=" * 60)

    gateway = LLMGateway()

    accounts = [
        AccountConfig(id="acc-1", name="Low Balance", api_key="sk-1", weight=1.0, remaining_balance=50.0),
        AccountConfig(id="acc-2", name="High Weight", api_key="sk-2", weight=3.0, remaining_balance=50.0),
        AccountConfig(id="acc-3", name="Normal", api_key="sk-3", weight=1.0, remaining_balance=50.0),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    session_id = "sess-weighted"
    gateway.start_session(session_id)

    print("\nRouting decisions (high-weight account gets more requests):")
    for i in range(6):
        result = gateway.complete(session_id, f"Prompt {i+1}")
        acc_name = gateway.router.accounts[result["model"].split("/")[-1]].name if "/" in result.get("model", "") else "unknown"
        print(f"  Request {i+1} → {result['id'].split('-')[1]}")


def demo_sticky_session():
    """Demonstrate sticky session behavior."""
    print("\n" + "=" * 60)
    print("DEMO: Sticky Session (stays on same account across turns)")
    print("=" * 60)

    gateway = LLMGateway()

    accounts = [
        AccountConfig(id="acc-1", name="Account A", api_key="sk-a", weight=1.0, remaining_balance=100.0),
        AccountConfig(id="acc-2", name="Account B", api_key="sk-b", weight=1.0, remaining_balance=100.0),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    session_id = "sess-sticky"
    gateway.start_session(session_id)

    print("\nMulti-turn conversation (stays on Account A):")
    prompts = [
        "What is the capital of France?",
        "What is the capital of Germany?",
        "What is the capital of Italy?",
        "What is the capital of Spain?",
        "What is the capital of Portugal?",
    ]

    for prompt in prompts:
        result = gateway.complete(session_id, prompt)
        model = result.get("model", "")
        print(f"  Q: {prompt[:40]}... → {model}")

    # Now exhaust Account A's balance
    print("\n--- Exhausting Account A ---")
    for i in range(10):
        result = gateway.complete(session_id, f"Exhaust prompt {i+1}")
        model = result.get("model", "")
        print(f"  Request {i+1} → {model}")

    print("\n--- Now routing to Account B ---")
    for i in range(3):
        result = gateway.complete(session_id, f"After-exhaust prompt {i+1}")
        model = result.get("model", "")
        print(f"  Request {i+1} → {model}")


def demo_fallback():
    """Demonstrate automatic fallback when an account is rate-limited."""
    print("\n" + "=" * 60)
    print("DEMO: Automatic Fallback (Account A simulated as rate-limited)")
    print("=" * 60)

    gateway = LLMGateway()

    accounts = [
        AccountConfig(id="acc-1", name="Primary (rate-limited)", api_key="sk-a", weight=1.0, remaining_balance=100.0),
        AccountConfig(id="acc-2", name="Fallback", api_key="sk-b", weight=1.0, remaining_balance=100.0),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    session_id = "sess-fallback"
    gateway.start_session(session_id)

    # First few requests go to Account A (sticky)
    print("\nRequests 1-3: Using Account A (sticky)")
    for i in range(3):
        result = gateway.complete(session_id, f"Fallback test {i+1}")
        model = result.get("model", "")
        print(f"  Request {i+1} → {model}")

    # Simulate rate limit on Account A
    acc1 = gateway.router.accounts["acc-1"]
    acc1.status = AccountStatus.RATE_LIMITED
    acc1.remaining_balance = 0.0

    print("\nAccount A is now rate-limited. Fallback to Account B:")
    for i in range(3):
        result = gateway.complete(session_id, f"Post-rate-limit {i+1}")
        model = result.get("model", "")
        print(f"  Request {i+1} → {model}")


def demo_virtual_pool():
    """Demonstrate the virtual pool abstraction."""
    print("\n" + "=" * 60)
    print("DEMO: Virtual Pool Abstraction")
    print("=" * 60)

    gateway = LLMGateway()

    accounts = [
        AccountConfig(id="acc-1", name="Dev Account", api_key="sk-dev", weight=1.0, remaining_balance=25.0),
        AccountConfig(id="acc-2", name="Prod Account", api_key="sk-prod", weight=1.0, remaining_balance=75.0),
        AccountConfig(id="acc-3", name="Staging Account", api_key="sk-staging", weight=1.0, remaining_balance=50.0),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    session_id = "sess-pool"
    gateway.start_session(session_id)

    print("\nVirtual Pool View:")
    pool = gateway.get_virtual_pool()
    print(json.dumps(pool, indent=2))


if __name__ == "__main__":
    demo_basic_routing()
    demo_weighted_routing()
    demo_sticky_session()
    demo_fallback()
    demo_virtual_pool()
