#!/usr/bin/env python3
"""
LLM Gateway - Zed Plugin Demo

This script demonstrates the core gateway logic that powers the Zed plugin.
Run this to see the routing engine in action without needing Rust tooling.

Usage:
    python demo.py

Or install as a package and use it directly in your project.
"""

import sys
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import time
import json
import hashlib


# ─── Enums and Data Structures ─────────────────────────────────────────────

class AccountStatus(Enum):
    """Status of an LLM account."""
    HEALTHY = "healthy"
    RATE_LIMITED = "rate_limited"
    MAINTENANCE = "maintenance"
    EXHAUSTED = "exhausted"


@dataclass
class AccountConfig:
    """Configuration for a single LLM account."""
    id: str
    name: str
    api_key_hash: str
    base_url: str = "https://api.anthropic.com"
    model: str = "claude-3-5-sonnet-20241022"
    max_tokens: int = 8192
    weight: float = 1.0
    enabled: bool = True
    status: AccountStatus = AccountStatus.HEALTHY
    remaining_balance: float = 0.0
    tokens_used: int = 0
    total_cost_usd: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_used: Optional[str] = None
    budget_limit: float = 0.0  # 0 = no limit


@dataclass
class SessionState:
    """State for a single conversation session."""
    id: str
    started_at: float
    current_account_id: Optional[str]
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0


@dataclass
class RoutingDecision:
    """Result of the routing algorithm."""
    account_id: Optional[str]
    model: str
    score: float
    reason: str


# ─── Core Components ──────────────────────────────────────────────────────

class AccountRouter:
    """Routes requests to accounts based on balance, health, and weights."""

    def __init__(self):
        self.accounts: Dict[str, AccountConfig] = {}
        self.cost_trackers: Dict[str, float] = {}
        self.request_counts: Dict[str, List[float]] = {}

    def register_account(self, config: AccountConfig) -> str:
        """Register a new account in memory."""
        self.accounts[config.id] = config
        self.cost_trackers[config.id] = 0.0
        self.request_counts[config.id] = []
        return config.id

    def unregister_account(self, account_id: str) -> None:
        """Remove an account."""
        if account_id in self.accounts:
            del self.accounts[account_id]
            del self.cost_trackers[account_id]
            del self.request_counts[account_id]

    def _compute_score(self, account: AccountConfig) -> Tuple[float, str]:
        """Compute a routing score for a single account."""
        if not account.enabled or account.status != AccountStatus.HEALTHY:
            return 0.0, "disabled"

        # Base score: proportional share of the pool
        total_balance = sum(
            acc.remaining_balance for acc in self.accounts.values()
            if acc.enabled and acc.status == AccountStatus.HEALTHY
        )
        if total_balance <= 0:
            return 0.0, "no_balance"

        base_score = (account.remaining_balance / total_balance) * account.weight

        # Health factor
        health_factor = {
            AccountStatus.HEALTHY: 1.0,
            AccountStatus.RATE_LIMITED: 0.3,
            AccountStatus.MAINTENANCE: 0.5,
            AccountStatus.EXHAUSTED: 0.0,
        }.get(account.status, 1.0)

        # Rate limit factor (simplified for demo)
        rate_limit_factor = 1.0

        # Latency factor (simplified - assume all accounts are fast)
        latency_factor = 1.0

        score = base_score * health_factor * rate_limit_factor * latency_factor
        return score, f"balance={account.remaining_balance:.2f}, weight={account.weight}"

    def route_request(
        self,
        session_id: Optional[str],
        prompt: str,
        max_tokens: int = 4096,
        force_account: Optional[str] = None,
    ) -> RoutingDecision:
        """Route a request to the best available account."""

        # Step 1: Check if we have any healthy accounts
        healthy_accounts = [
            acc for acc in self.accounts.values()
            if acc.enabled and acc.status == AccountStatus.HEALTHY
        ]

        if not healthy_accounts:
            return RoutingDecision(
                account_id=None, model="none", score=0.0,
                reason="No healthy accounts available"
            )

        # Step 2: Check sticky sessions (disabled by default)
        if session_id and self._is_sticky_session_enabled():
            current_account = self._get_current_session(session_id)
            if current_account and current_account in self.accounts:
                score, reason = self._compute_score(self.accounts[current_account])
                return RoutingDecision(
                    account_id=current_account, model=self.accounts[current_account].model,
                    score=score, reason=f"sticky_session:{current_account}"
                )

        # Step 3: Score all healthy accounts
        scored = [(aid, acc, self._compute_score(acc)) for aid, acc in self.accounts.items()
                  if acc.enabled and acc.status == AccountStatus.HEALTHY]

        if not scored:
            return RoutingDecision(account_id=None, model="none", score=0.0, reason="no_healthy_accounts")

        # Sort by score descending
        scored.sort(key=lambda x: -x[2])

        best_account_id, best_account, best_score = scored[0][0], scored[0][1], scored[0][2]

        # Step 4: Check budget constraints
        if best_account.budget_limit > 0:
            remaining = best_account.budget_limit - self.cost_trackers.get(best_account_id, 0.0)
            if remaining <= 0:
                return RoutingDecision(
                    account_id=None, model="none", score=0.0,
                    reason=f"budget_exhausted:{best_account_id}"
                )

        # Step 5: Select the best account
        return RoutingDecision(
            account_id=best_account_id,
            model=best_account.model,
            score=best_score,
            reason=f"score={best_score:.4f}, {best_account.name}"
        )

    def _is_sticky_session_enabled(self) -> bool:
        """Check if sticky sessions are enabled."""
        return False  # Disabled by default; enable via config

    def _get_current_session(self, session_id: str) -> Optional[str]:
        """Get the current account for a sticky session."""
        return None

    def update_request_result(self, account_id: str, result: Dict[str, Any]) -> None:
        """Record the result of a request for accounting."""
        if account_id not in self.accounts:
            return

        cost = result.get("cost", 0.0)
        input_tokens = result.get("usage", {}).get("input_tokens", 0) or 0
        output_tokens = result.get("usage", {}).get("output_tokens", 0) or 0

        # Update cost tracker
        self.cost_trackers[account_id] += cost

        # Update tokens used
        self.accounts[account_id].tokens_used += input_tokens + output_tokens

        # Update last_used timestamp
        self.accounts[account_id].last_used = datetime.utcnow().isoformat()

        # Track for rate limiting
        self.request_counts[account_id].append(time.time())


class BalanceTracker:
    """Tracks balance across multiple accounts and provides a virtual pool view."""

    def __init__(self, router: AccountRouter):
        self.router = router

    def get_virtual_pool_balance(self) -> Dict[str, Any]:
        """Get the aggregated balance across all accounts."""
        total_balance = sum(
            acc.remaining_balance for acc in self.router.accounts.values()
            if acc.enabled and acc.status == AccountStatus.HEALTHY
        )
        total_tokens_used = sum(acc.tokens_used for acc in self.router.accounts.values())

        return {
            "pool_name": "LLM Gateway Pool",
            "balance_usd": round(total_balance, 2),
            "tokens_available": int(total_balance * 1e6 / 3e-6) if total_balance > 0 else 0,
            "accounts": [
                {
                    "id": acc.id,
                    "name": acc.name,
                    "balance": round(acc.remaining_balance, 2),
                    "status": acc.status.value,
                }
                for acc in self.router.accounts.values()
                if acc.enabled
            ],
        }

    def get_allocation(self) -> Dict[str, Any]:
        """Get the proportional allocation of the virtual pool."""
        total = sum(acc.remaining_balance for acc in self.router.accounts.values()
                    if acc.enabled and acc.status == AccountStatus.HEALTHY)
        if total <= 0:
            return {}

        return {
            "total": round(total, 2),
            "accounts": [
                {
                    "id": acc.id,
                    "percentage": round(acc.remaining_balance / total * 100, 2),
                }
                for acc in self.router.accounts.values()
                if acc.enabled and acc.status == AccountStatus.HEALTHY
            ],
        }


class TokenCounter:
    """Estimates and tracks token usage across models."""

    MODEL_COSTS = {
        "claude-3-haiku": {"input": 0.25e-6, "output": 1.25e-6},
        "claude-3-sonnet": {"input": 3e-6, "output": 15e-6},
        "claude-3-5-sonnet": {"input": 3e-6, "output": 15e-6},
        "claude-3-opus": {"input": 15e-6, "output": 75e-6},
        "codellama-7b": {"input": 0.0, "output": 0.0},
    }

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate the cost of a request."""
        rate = self.MODEL_COSTS.get(model, {"input": 3e-6, "output": 15e-6})
        return input_tokens * rate["input"] + output_tokens * rate["output"]


# ─── Main Gateway Class ───────────────────────────────────────────────────

class LLMGateway:
    """Main LLM Gateway that orchestrates routing, cost tracking, and sessions."""

    def __init__(self, db_path: Optional[str] = None):
        self.router = AccountRouter()
        self.tracker = BalanceTracker(self.router)
        self.token_counter = TokenCounter(None)  # Doesn't need router ref
        self.db_path = db_path or os.path.join(os.path.dirname(__file__), "gateway.db")
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                api_key_hash TEXT NOT NULL,
                base_url TEXT NOT NULL DEFAULT 'https://api.anthropic.com',
                model TEXT NOT NULL DEFAULT 'claude-3-5-sonnet-20241022',
                max_tokens INTEGER NOT NULL DEFAULT 8192,
                weight REAL NOT NULL DEFAULT 1.0,
                enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'healthy',
                remaining_balance REAL NOT NULL DEFAULT 0.0,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                total_cost_usd REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                last_used TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                started_at REAL NOT NULL,
                current_account_id TEXT,
                total_tokens_used INTEGER DEFAULT 0,
                total_cost_usd REAL DEFAULT 0.0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS request_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt TEXT NOT NULL,
                response_text TEXT,
                usage_input_tokens INTEGER,
                usage_output_tokens INTEGER,
                cost_usd REAL,
                latency_ms REAL,
                error TEXT,
                timestamp REAL NOT NULL
            )
        """)

        conn.commit()
        conn.close()

    def register_account(self, config: AccountConfig) -> str:
        """Register a new account (in-memory + database)."""
        api_key_hash = hashlib.sha256(config.api_key.encode()).hexdigest()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO accounts (
                id, name, api_key_hash, base_url, model, max_tokens,
                weight, enabled, status, remaining_balance, tokens_used,
                total_cost_usd, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            config.id, config.name, api_key_hash, config.base_url,
            config.model, config.max_tokens, config.weight, 1 if config.enabled else 0,
            config.status.value if hasattr(config, "status") else "healthy",
            config.remaining_balance, 0, 0.0,
            datetime.utcnow().isoformat(),
        ))

        conn.commit()
        conn.close()

        self.router.register_account(config)
        return config.id

    def unregister_account(self, account_id: str) -> None:
        """Unregister an account."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        conn.commit()
        conn.close()

        self.router.unregister_account(account_id)

    def complete(
        self,
        session_id: str,
        prompt: str,
        max_tokens: int = 4096,
        force_account: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a completion request through the gateway."""

        # Route the request
        decision = self.router.route_request(session_id, prompt, max_tokens=max_tokens)

        if not decision.account_id:
            return {
                "error": {
                    "type": "routing_error",
                    "message": decision.reason,
                },
            }

        account = self.router.accounts[decision.account_id]

        # In a real implementation, this would forward to the actual Claude API.
        # For the plugin/demo, we return a mock response.
        cost = self.token_counter.estimate_cost(account.model, 128, 64)

        result = {
            "id": f"{account.id}-cm-{int(time.time_ns())}",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"[ROUTED TO {account.name}] Model: {account.model} | "
                        f"Cost estimate: ${cost:.6f}"
                    ),
                }
            ],
            "model": account.model,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 128,
                "output_tokens": 64,
            },
            "cost": cost,
        }

        # Record the result
        self.router.update_request_result(decision.account_id, result)

        # Log the request
        self._log_request(
            session_id=session_id,
            account_id=decision.account_id,
            prompt=prompt,
            response=result,
        )

        return result

    def _log_request(self, session_id: str, account_id: str, prompt: str,
                     response: Dict[str, Any]) -> None:
        """Log a request for auditing."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        error = json.dumps(response.get("error", {})) if "error" in response else None

        cursor.execute("""
            INSERT INTO request_log (session_id, account_id, model, prompt,
                response_text, usage_input_tokens, usage_output_tokens,
                cost_usd, latency_ms, error, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id, account_id, response.get("model", ""),
            prompt[:500], json.dumps(response.get("content", [])),
            response.get("usage", {}).get("input_tokens", 0),
            response.get("usage", {}).get("output_tokens", 0),
            response.get("cost", 0.0), 0.0, error,
            time.time(),
        ))

        conn.commit()
        conn.close()

    def get_account_stats(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Get stats for a specific account."""
        if account_id not in self.router.accounts:
            return None

        account = self.router.accounts[account_id]
        cost = self.cost_trackers.get(account_id, 0.0)

        return {
            "id": account.id,
            "name": account.name,
            "status": account.status.value,
            "remaining_balance": round(account.remaining_balance, 2),
            "tokens_used": account.tokens_used,
            "total_cost_usd": round(cost, 4),
        }

    def get_virtual_pool(self) -> Dict[str, Any]:
        """Get the virtual pool view."""
        return self.tracker.get_virtual_pool_balance()


# ─── Demo ───────────────────────────────────────────────────────────────────

def main():
    """Run the gateway demo."""
    print("=" * 70)
    print("LLM GATEWAY - ZED PLUGIN DEMO")
    print("=" * 70)

    # Create gateway instance
    gateway = LLMGateway()

    # Register accounts
    print("\n📝 Registering accounts...")

    gateway.register_account(AccountConfig(
        id="acc-alpha", name="Team Alpha (Premium)", api_key="sk-team-alpha-***",
        remaining_balance=100.0, model="claude-3-5-sonnet-20241022"
    ))

    gateway.register_account(AccountConfig(
        id="acc-beta", name="Team Beta (Budget)", api_key="sk-team-beta-***",
        remaining_balance=50.0, model="claude-3-haiku-20240307"
    ))

    gateway.register_account(AccountConfig(
        id="acc-local", name="Local Ollama (Free)", api_key="ollama",
        remaining_balance=float("inf"), model="codellama-7b"
    ))

    # Show virtual pool
    print("\n📊 Virtual Pool:")
    print(json.dumps(gateway.get_virtual_pool(), indent=2))

    # Demo routing
    print("\n🧪 Routing Demo:")
    print("-" * 50)

    test_prompts = [
        ("What is the capital of France?", "general_chat"),
        ("Write a Python function to sort a list", "code_generation"),
        ("Explain quantum entanglement", "reasoning"),
        ("Write a short story about a robot", "creative_writing"),
    ]

    for prompt, _ in test_prompts:
        result = gateway.complete("demo-session", prompt, max_tokens=128)
        print(f"\n  Prompt: {prompt[:50]}...")
        print(f"  → {result.get('content', [{}])[0].get('text', 'N/A')}")

    # Show account stats
    print("\n📈 Account Stats:")
    for acc in gateway.router.accounts.values():
        stats = gateway.get_account_stats(acc.id)
        if stats:
            print(f"  {stats['name']}: ${stats['remaining_balance']:.2f} remaining")

    print("\n✅ Demo complete!")


if __name__ == "__main__":
    main()
