#!/usr/bin/env python3
"""
Cost Savings Demo — Show how the LLM Gateway reduces token usage and costs.

This script demonstrates:
1. Task-based model routing (cheaper models for simple tasks)
2. Budget enforcement (hard stop at budget limit)
3. Savings calculation vs. naive single-account approach
4. Token estimation and prediction
"""

import sys
sys.path.insert(0, str(__file__[:-5]))

from gateway import LLMGateway, AccountConfig
from cost_optimizer import CostOptimizer, MODEL_COSTS, CostStrategy


def demo_cost_savings():
    """Demonstrate cost savings from smart routing."""
    print("=" * 70)
    print("COST SAVINGS DEMO")
    print("=" * 70)

    # Setup: two accounts with different budgets
    gateway = LLMGateway()

    account_china = AccountConfig(
        id="acc-china",
        name="China Team Budget",
        api_key="sk-china-key",
        remaining_balance=20.0,
    )
    gateway.register_account(account_china)

    account_india = AccountConfig(
        id="acc-india",
        name="India Team Budget",
        api_key="sk-india-key",
        remaining_balance=50.0,
    )
    gateway.register_account(account_india)

    optimizer = CostOptimizer(gateway)

    # Configure budgets
    optimizer.configure_budget("acc-china", limit_usd=10.0, warning_threshold_pct=80)
    optimizer.configure_budget("acc-india", limit_usd=20.0, warning_threshold_pct=85)

    print("\n--- Setup ---")
    print(f"  Account 'acc-china':   ${account_china.remaining_balance:.2f} balance, $10 budget")
    print(f"  Account 'acc-india':   ${account_india.remaining_balance:.2f} balance, $20 budget")
    print(f"  Total pool:            ${gateway.get_virtual_pool()['balance_usd']:.2f}")

    # ─── Scenario 1: Naive routing (always uses most expensive model) ─────────

    print("\n--- Scenario 1: Naive Routing (no optimization) ---")
    naive_cost = 0.0
    naive_requests = []

    prompts = [
        "What is the capital of France?",
        "Write a Python function to reverse a string",
        "Explain quantum entanglement in simple terms",
        "Tell me a joke about programmers",
        "Write a React component with TypeScript types",
        "Solve: if f(x) = x^2 + 3x + 2, find f(5)",
    ]

    for prompt in prompts:
        # Naive: always use the most expensive account
        result = gateway.complete("sess-naive", prompt, model="claude-3-5-sonnet")
        naive_cost += result.get("cost", 0.0)
        naive_requests.append({
            "prompt": prompt[:40],
            "cost": result.get("cost", 0),
        })

    print(f"  Total cost (naive):   ${naive_cost:.6f}")
    for req in naive_requests:
        print(f"    '{req['prompt']}' → ${req['cost']:.6f}")

    # ─── Scenario 2: Cost-aware routing ──────────────────────────────────────

    print("\n--- Scenario 2: Cost-Aware Routing ---")
    smart_cost = 0.0
    smart_requests = []

    for prompt in prompts:
        result = optimizer.optimize_request(prompt)
        if "error" in result:
            print(f"  '{prompt[:40]}' → ERROR: {result['error']['message']}")
        else:
            cost = result.get("estimated_cost_usd", 0.0)
            smart_cost += cost
            smart_requests.append({
                "prompt": prompt[:40],
                "model": result.get("selected_model", "unknown"),
                "cost": cost,
                "note": result.get("cost_savings_note", ""),
            })

    print(f"  Total cost (smart):   ${smart_cost:.6f}")
    for req in smart_requests:
        print(f"    '{req['prompt']}' → {req['model'][:30]:<30} ${req['cost']:.6f} "
              f"{req['note']}")

    # ─── Scenario 3: Budget enforcement ──────────────────────────────────────

    print("\n--- Scenario 3: Budget Enforcement ---")
    print("  Request that would exceed budget:")
    expensive_prompt = "Write a complete React + TypeScript + Redux application " \
                      "with authentication, database schema, API routes, " \
                      "and unit tests. Include error handling, loading states, " \
                      "and edge cases."

    result = optimizer.optimize_request(expensive_prompt)
    print(f"  Prompt: {expensive_prompt[:50]}...")
    if "error" in result:
        print(f"  Result: {result['error']['message']}")
    else:
        print(f"  Result: ${result.get('estimated_cost_usd', 0):.6f}")

    # ─── Scenario 4: Savings summary ─────────────────────────────────────────

    print("\n--- Savings Summary ---")
    savings = optimizer.get_savings_summary()
    print(f"  Total savings:        ${savings['total_savings_usd']:.4f} ({savings['savings_percentage']:.1f}% reduction)")
    print(f"  Without optimization, cost would be ~${naive_cost:.6f}")
    print(f"  With optimization, cost is ~${smart_cost:.6f}")

    # ─── Scenario 5: Budget reset (admin) ──────────────────────────────────

    print("\n--- Scenario 4: Budget Reset ---")
    allowed, reason = optimizer.check_budget("acc-china", estimated_cost=0.001)
    print(f"  Check budget for acc-china: allowed={allowed}, reason={reason}")

    # Reset the budget
    optimizer.reset_budget("acc-china", new_limit=15.0)
    print(f"  Budget reset to $15.00")
    allowed, reason = optimizer.check_budget("acc-china", estimated_cost=0.001)
    print(f"  Check again: allowed={allowed}, reason={reason}")


def demo_token_estimation():
    """Demonstrate token estimation."""
    print("\n" + "=" * 70)
    print("TOKEN ESTIMATION DEMO")
    print("=" * 70)

    optimizer = CostOptimizer(LLMGateway())

    prompts = [
        "Hello",
        "Explain quantum computing in simple terms",
        "Write a Python function to merge two sorted arrays. Include type hints and docstring.",
    ]

    for prompt in prompts:
        input_tokens, output_tokens = optimizer.estimate_tokens(prompt, max_tokens=4096)
        cost = (input_tokens * MODEL_COSTS["claude-3-haiku"].cost_per_token_input +
                output_tokens * MODEL_COSTS["claude-3-haiku"].cost_per_token_output)
        print(f"  Prompt: {prompt[:50]:<50} "
              f"→ {input_tokens:>4} input + {output_tokens:>4} output tokens "
              f"= ${cost:.6f}")


if __name__ == "__main__":
    demo_cost_savings()
    demo_token_estimation()
