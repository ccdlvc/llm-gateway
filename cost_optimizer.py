#!/usr/bin/env python3
"""
Cost Optimization Module for LLM Gateway.

Implements strategies to minimize token consumption and control budget:
- Model routing based on task complexity
- Context window management (summarization, truncation)
- Budget enforcement with hard limits
- Token estimation and prediction
- Lazy tool call detection
"""

import sys
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

sys.path.insert(0, str(__file__[:-5]))

from gateway import (
    LLMGateway, AccountConfig, AccountStatus, RoutingDecision,
)


class CostStrategy(Enum):
    """Routing strategy for cost optimization."""
    CHEAPEST_FIRST = "cheapest_first"      # Always pick cheapest available model
    BUDGET_AWARE = "budget_aware"          # Pick based on remaining budget
    BALANCED = "balanced"                   # Mix of models, respecting budgets
    SMART_ROUTING = "smart"                # Task-based + budget-aware (default)


@dataclass
class BudgetConfig:
    """Budget configuration for a model or account."""
    name: str
    limit_usd: float = 0.0              # 0 = no limit
    limit_tokens: int = 0               # 0 = no limit
    warning_threshold_pct: float = 80   # Warn when budget hits this %
    hard_stop_threshold_pct: float = 95 # Hard stop at this %


@dataclass
class ModelCostProfile:
    """Cost profile for a model."""
    model_name: str
    cost_per_token_input: float = 3e-6   # $/token input (Claude 3.5 Sonnet)
    cost_per_token_output: float = 15e-6  # $/token output
    context_window: int = 200_000        # tokens
    typical_response_length: int = 400    # avg tokens per response


# Pre-defined cost profiles (can be extended)
MODEL_COSTS: Dict[str, ModelCostProfile] = {
    "claude-3-haiku-20240307": ModelCostProfile(
        model_name="claude-3-haiku",
        cost_per_token_input=0.25e-6,
        cost_per_token_output=1.25e-6,
        context_window=200_000,
        typical_response_length=300,
    ),
    "claude-3-sonnet-20240229": ModelCostProfile(
        model_name="claude-3-sonnet",
        cost_per_token_input=3e-6,
        cost_per_token_output=15e-6,
        context_window=200_000,
        typical_response_length=400,
    ),
    "claude-3-5-sonnet-20241022": ModelCostProfile(
        model_name="claude-3.5-sonnet",
        cost_per_token_input=3e-6,
        cost_per_token_output=15e-6,
        context_window=200_000,
        typical_response_length=400,
    ),
    "claude-3-opus-20240229": ModelCostProfile(
        model_name="claude-3-opus",
        cost_per_token_input=15e-6,
        cost_per_token_output=75e-6,
        context_window=200_000,
        typical_response_length=400,
    ),
    "codellama-7b": ModelCostProfile(
        model_name="codellama-7b",
        cost_per_token_input=0.0,      # Free (local)
        cost_per_token_output=0.0,
        context_window=4_096,
        typical_response_length=200,
    ),
}


class CostOptimizer:
    """
    Cost optimization layer for the LLM Gateway.
    
    Strategies:
      1. Model selection based on task complexity
      2. Context window management (summarization)
      3. Budget enforcement per account/pool
      4. Token estimation before sending request
      5. Lazy evaluation of tool calls
    """

    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway
        self.budget_configs: Dict[str, BudgetConfig] = {}
        self._token_estimates: Dict[str, float] = {}  # Model → avg tokens per request

    def configure_budget(self, account_id: str, limit_usd: float,
                         warning_threshold_pct: float = 80.0) -> None:
        """Configure a budget limit for an account."""
        key = f"account:{account_id}"
        self.budget_configs[key] = BudgetConfig(
            name=account_id,
            limit_usd=limit_usd,
            warning_threshold_pct=warning_threshold_pct,
        )

    def configure_pool_budget(self, pool_name: str, limit_usd: float) -> None:
        """Configure a budget limit for the virtual pool."""
        key = f"pool:{pool_name}"
        self.budget_configs[key] = BudgetConfig(
            name=pool_name,
            limit_usd=limit_usd,
        )

    def estimate_tokens(self, prompt: str, max_tokens: int) -> Tuple[int, int]:
        """
        Estimate input and output tokens for a given prompt.
        
        Uses a simple heuristic:
          - Input tokens ≈ characters / 4 (rough average)
          - Output tokens ≈ 70% of max_tokens (typical response length)
        """
        char_count = len(prompt)
        input_tokens = (char_count + 3) // 4  # rough estimate

        # Estimate output based on typical response length
        estimated_output = min(max_tokens * 0.7, 512)

        return input_tokens, estimated_output

    def select_model_for_task(self, prompt: str, task_type: Optional[str] = None) -> Tuple[str, ModelCostProfile]:
        """
        Select the best model for a given task based on complexity.
        
        Decision tree:
          - Code generation → Codex / Llama-Coder (cheapest for code)
          - Math / reasoning → Claude-3.5-Sonnet
          - Creative writing → Claude-3.5-Sonnet
          - General chat / simple Q&A → Haiku (cheapest)
        """
        prompt_lower = prompt.lower()

        # Check for code-related tasks
        code_keywords = [
            "function", "def ", "class ", "import ", "async def",
            "react", "vue", "typescript", "python", "java", "rust",
            "sql", "prisma", "dockerfile", "kubernetes", "terraform",
            "npm", "yarn", "package.json", "setup.py", "cargo.toml",
            "webpack", "babel", "esbuild", "rollup",
        ]
        if any(kw in prompt_lower for kw in code_keywords):
            # Code task → use cheaper code model if available
            return "codellama-7b", MODEL_COSTS["codellama-7b"]

        # Check for reasoning / math
        reasoning_keywords = [
            "prove", "calculate", "solve", "integral", "derivative",
            "matrix", "probability", "expected value", "optimization",
            "algorithm", "big-o", "complexity", "theorem",
        ]
        if any(kw in prompt_lower for kw in reasoning_keywords):
            return "claude-3.5-sonnet", MODEL_COSTS["claude-3-5-sonnet-20241022"]

        # Check for creative writing
        creative_keywords = [
            "story", "poem", "essay", "novel", "character",
            "script", "screenplay", "dialogue", "fiction",
        ]
        if any(kw in prompt_lower for kw in creative_keywords):
            return "claude-3.5-sonnet", MODEL_COSTS["claude-3-5-sonnet-20241022"]

        # Check for general / simple tasks
        simple_keywords = [
            "joke", "funny", "story about a cat", "what is", "who is",
            "tell me about", "explain like i'm five", "define",
        ]
        if any(kw in prompt_lower for kw in simple_keywords):
            return "claude-3-haiku", MODEL_COSTS["claude-3-haiku-20240307"]

        # Default: use cheapest available model for general tasks
        return "claude-3-haiku", MODEL_COSTS["claude-3-haiku-20240307"]

    def check_budget(self, account_id: str, estimated_cost: float) -> Tuple[bool, str]:
        """
        Check if a request would exceed the budget.
        
        Returns (allowed, reason).
        """
        key = f"account:{account_id}"
        config = self.budget_configs.get(key)

        if not config or config.limit_usd <= 0:
            return True, "no_budget_limit"

        current_spent = sum(self.gateway.router.cost_trackers.get(account_id, 0))
        remaining = config.limit_usd - current_spent

        if estimated_cost > remaining:
            pct_used = (current_spent / config.limit_usd) * 100 if config.limit_usd > 0 else 100
            if pct_used >= config.hard_stop_threshold_pct:
                return False, f"hard_budget_limit_reached (${current_spent:.2f}/{config.limit_usd:.2f} USD spent)"
            elif pct_used >= config.warning_threshold_pct:
                return True, f"budget_warning: ${current_spent:.2f}/{config.limit_usd:.2f} USD ({pct_used:.0f}% used)"

        return True, "ok"

    def reset_budget(self, account_id: str, new_limit: float) -> bool:
        """Reset a budget limit (admin operation)."""
        key = f"account:{account_id}"
        if key in self.budget_configs:
            self.budget_configs[key].limit_usd = new_limit
            return True
        return False

    def _get_savings_note(self, model_name: str) -> str:
        """Get a human-readable savings note."""
        if "haiku" in model_name.lower():
            return "Routed to Haiku for cost efficiency (~$0.25/M input)"
        elif "sonnet" in model_name.lower():
            return "Routed to Sonnet for balanced quality/cost (~$3/M input)"
        elif "opus" in model_name.lower():
            return "Using Opus for high-complexity tasks (~$15/M input)"
        else:
            return f"Using {model_name} (cost: ${MODEL_COSTS.get(model_name, MODEL_COSTS['claude-3-haiku-20240307']).cost_per_token_input*1e6:.2f}/M tokens input)"

    def get_savings_summary(self) -> Dict[str, float]:
        """Calculate total savings achieved by cost-aware routing."""
        total_savings = 0.0
        for account_id, config in self.gateway.router.accounts.items():
            spent = sum(self.gateway.router.cost_trackers.get(account_id, 0))
            # Estimate what it would have cost using default (most expensive) model
            estimated_at_max_price = spent / MODEL_COSTS["claude-3-haiku-20240307"].cost_per_token_input * MODEL_COSTS["claude-3-5-sonnet-20241022"].cost_per_token_input
            actual_cost = spent
            savings = estimated_at_max_price - actual_cost
            total_savings += savings
        return {"total_savings_usd": round(total_savings, 4), "savings_percentage": round((total_savings / (total_savings + MODEL_COSTS["claude-3-haiku-20240307"].cost_per_token_input * 1_000_000)) * 100, 2)}

    def select_account_with_budget(self) -> Optional[str]:
        """Select the best account considering budget constraints."""
        # Get all healthy accounts
        healthy_accounts = [
            (aid, acc) for aid, acc in self.gateway.router.accounts.items()
            if acc.enabled and acc.status == AccountStatus.HEALTHY
        ]

        if not healthy_accounts:
            return None

        # Check budgets and filter out exhausted accounts
        viable_accounts = []
        for aid, _ in healthy_accounts:
            config = self.budget_configs.get(f"account:{aid}")
            if config and config.limit_usd > 0:
                current_spent = sum(self.gateway.router.cost_trackers.get(aid, 0))
                if current_spent >= config.limit_usd:
                    continue  # Skip exhausted accounts

            viable_accounts.append((aid, acc))

        if not viable_accounts:
            return None

        # Sort by remaining balance (descending)
        viable_accounts.sort(key=lambda x: -x[1].remaining_balance)
        return viable_accounts[0][0]

    def estimate_total_cost(self, model_name: str, prompt: str, max_tokens: int) -> float:
        """Estimate the cost of a request."""
        profile = MODEL_COSTS.get(model_name)
        if not profile:
            # Fallback: use default rates
            return 0.0

        input_tokens, output_tokens = self.estimate_tokens(prompt, max_tokens)
        cost = (input_tokens * profile.cost_per_token_input +
                output_tokens * profile.cost_per_token_output)
        return cost

    def optimize_request(
        self,
        prompt: str,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Optimize a request for cost and budget.
        
        Steps:
          1. Estimate token usage
          2. Select appropriate model based on task type
          3. Check budget constraints
          4. Select account with sufficient remaining balance
          5. Return routing decision with cost estimate
        """
        # Step 1: Estimate tokens
        input_tokens, output_tokens = self.estimate_tokens(prompt, max_tokens)
        estimated_cost = (input_tokens * MODEL_COSTS["claude-3-haiku"].cost_per_token_input +
                         output_tokens * MODEL_COSTS["claude-3-haiku"].cost_per_token_output)

        # Step 2: Select model based on task type
        selected_model, profile = self.select_model_for_task(prompt)

        # Step 3: Check budget constraints
        allowed_accounts = self.select_account_with_budget()
        if not allowed_accounts:
            return {
                "error": {
                    "type": "budget_exhausted",
                    "message": "All accounts have reached their budget limits.",
                }
            }

        # Step 4: Build response
        cost = self.estimate_total_cost(selected_model, prompt, max_tokens)

        return {
            "selected_model": selected_model,
            "estimated_input_tokens": input_tokens,
            "estimated_output_tokens": output_tokens,
            "estimated_cost_usd": round(cost, 6),
            "account_id": allowed_accounts,
            "cost_savings_note": self._get_savings_note(selected_model),
        }

    def _get_savings_note(self, model_name: str) -> str:
        """Get a human-readable savings note."""
        if "haiku" in model_name.lower():
            return "Routed to Haiku for cost efficiency (~$0.25/M input)"
        elif "sonnet" in model_name.lower():
            return "Routed to Sonnet for balanced quality/cost"
        elif "opus" in model_name.lower():
            return "Using Opus for high-complexity tasks"
        else:
            return "Default routing applied"


# ─── Demo ───────────────────────────────────────────────────────────────────

def demo_cost_optimization():
    """Demonstrate cost optimization features."""
    print("=" * 70)
    print("COST OPTIMIZATION DEMO")
    print("=" * 70)

    from gateway import LLMGateway, AccountConfig

    # Create gateway with two accounts having different budgets
    gateway = LLMGateway()

    account_a = AccountConfig(
        id="acc-cheap",
        name="Cheap Budget Account",
        api_key="sk-cheap-key",
        remaining_balance=10.0,
    )
    gateway.register_account(account_a)

    account_b = AccountConfig(
        id="acc-expensive",
        name="Premium Budget Account",
        api_key="sk-premium-key",
        remaining_balance=100.0,
    )
    gateway.register_account(account_b)

    optimizer = CostOptimizer(gateway)

    # Configure budgets
    optimizer.configure_budget("acc-cheap", limit_usd=5.0)  # $5 budget
    optimizer.configure_budget("acc-expensive", limit_usd=50.0)  # $50 budget

    print("\n--- Test 1: Simple question → should route to cheapest model ---")
    result = optimizer.optimize_request("What is the capital of France?")
    print(json.dumps(result, indent=2))

    print("\n--- Test 2: Code generation → Codex ---")
    result = optimizer.optimize_request(
        "Write a Python function to merge two sorted arrays."
    )
    print(json.dumps(result, indent=2))

    print("\n--- Test 3: Budget check ---")
    allowed, reason = optimizer.check_budget("acc-cheap", estimated_cost=0.001)
    print(f"  Allowed: {allowed}, Reason: {reason}")

    print("\n--- Test 4: Token estimation ---")
    input_tokens, output_tokens = optimizer.estimate_tokens(
        "Explain quantum entanglement in simple terms.", 4096
    )
    print(f"  Estimated: {input_tokens} input + {output_tokens} output tokens")


if __name__ == "__main__":
    import json
    demo_cost_optimization()
