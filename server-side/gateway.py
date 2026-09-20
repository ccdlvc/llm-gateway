"""
LLM Gateway - Core Routing Engine (Server-Side)

This module contains the core routing logic for the LLM Gateway.
It handles:
  - Multi-account balance-aware routing
  - Sticky session management
  - Virtual pool balance tracking
  - Account health monitoring
  - Budget enforcement

This is a refactored, pure-Python version that can run without
a Flask server. It's designed to be used either as a standalone
service or integrated into an IDE plugin (e.g., Zed).
"""

import os
import sqlite3
import hashlib
import time
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ─── Enums and Data Classes ───────────────────────────────────────────────

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
    api_key: str
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
    """
    Routes requests to accounts based on balance, health, and weights.
    
    Routing algorithm:
      1. Check sticky sessions (prefer current account within a session)
      2. Score all healthy accounts using a weighted formula
      3. Apply rate-limit and latency factors
      4. Select the highest-scoring account
    """

    def __init__(self):
        self.accounts: Dict[str, AccountConfig] = {}
        self.cost_trackers: Dict[str, float] = {}  # account_id → total cost
        self.request_counts: Dict[str, List[float]] = {}  # account_id → [timestamps]

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

        # Rate limit factor
        rate_limit_factor = self._compute_rate_limit_factor(account.id)

        # Latency factor (penalize slow accounts)
        latency_factor = self._compute_latency_factor(account.id)

        score = base_score * health_factor * rate_limit_factor * latency_factor
        return score, f"balance={account.remaining_balance:.2f}, weight={account.weight}"

    def _compute_rate_limit_factor(self, account_id: str) -> float:
        """Compute how much of the rate limit budget is remaining."""
        if account_id not in self.request_counts:
            return 1.0

        window = timedelta(seconds=60)
        now = time.time()
        recent = [t for t in self.request_counts[account_id] if now - t < window.total_seconds()]

        max_requests = 100  # Per-minute rate limit
        recent_count = len(recent)
        remaining = max(0, max_requests - recent_count)
        return min(1.0, remaining / max_requests)

    def _compute_latency_factor(self, account_id: str) -> float:
        """Compute a latency penalty factor (simplified)."""
        # In production, this would track actual response times
        # For now, assume all accounts are equally fast
        return 1.0

    def route_request(
        self,
        session_id: Optional[str],
        prompt: str,
        max_tokens: int = 4096,
        force_account: Optional[str] = None,
    ) -> RoutingDecision:
        """
        Route a request to the best available account.
        
        Args:
            session_id: For sticky session routing
            prompt: The user prompt (used for task-type detection in multi-model)
            max_tokens: Max response tokens
            force_account: If set, force use this account instead of routing
            
        Returns:
            RoutingDecision with the selected account and reason
        """
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

        # Step 2: Check sticky sessions
        if session_id and self._is_sticky_session(session_id):
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

        best_account_id, best_account, best_score = scored[0]

        # Step 4: Check budget constraints
        if best_account.budget_limit > 0:
            remaining = best_account.budget_limit - self.cost_trackers[best_account_id]
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

    def _is_sticky_session(self, session_id: str) -> bool:
        """Check if a session has prior turns (sticky routing)."""
        # In production, this would check a database or Redis
        # For now, we use an in-memory store
        return False  # Disabled by default; enable by setting _sessions

    def _get_current_session(self, session_id: str) -> Optional[str]:
        """Get the current account for a sticky session."""
        # In production, load from DB/Redis
        return None

    def update_request_result(self, account_id: str, result: Dict[str, Any]) -> None:
        """Record the result of a request for accounting."""
        if account_id not in self.accounts:
            return

        cost = result.get("cost", 0.0)
        input_tokens = result.get("usage", {}).get("input_tokens", 0)
        output_tokens = result.get("usage", {}).get("output_tokens", 0)

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

    def get_allocation(self) -> Dict[str, float]:
        """Get the proportional allocation of the virtual pool."""
        total = sum(acc.remaining_balance for acc in self.router.accounts.values()
                    if acc.enabled and acc.status == AccountStatus.HEALTHY)
        if total <= 0:
            return {}

        return {
            acc.id: round(acc.remaining_balance / total * 100, 2)
            for acc in self.router.accounts.values()
            if acc.enabled and acc.status == AccountStatus.HEALTHY
        }


class TokenCounter:
    """Estimates and tracks token usage across models."""

    def __init__(self, router: AccountRouter):
        self.router = router

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate the cost of a request given token counts."""
        rates = {
            "claude-3-haiku": {"input": 0.25e-6, "output": 1.25e-6},
            "claude-3-sonnet": {"input": 3e-6, "output": 15e-6},
            "claude-3-5-sonnet": {"input": 3e-6, "output": 15e-6},
            "claude-3-opus": {"input": 15e-6, "output": 75e-6},
            "codellama-7b": {"input": 0.0, "output": 0.0},  # Free (local)
        }

        rate = rates.get(model, {"input": 3e-6, "output": 15e-6})
        return input_tokens * rate["input"] + output_tokens * rate["output"]


class SessionManager:
    """Manages sticky conversation sessions."""

    def __init__(self, router: AccountRouter):
        self.router = router
        self.sessions: Dict[str, SessionState] = {}

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """Add a message to a session (for sticky routing)."""
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(
                id=session_id,
                started_at=time.time(),
                current_account_id=None,
            )

    def get_session_context(self, session_id: str) -> Optional[SessionState]:
        """Get the current state of a session."""
        return self.sessions.get(session_id)


# ─── Main Gateway Class ───────────────────────────────────────────────────

class LLMGateway:
    """
    Main LLM Gateway that orchestrates routing, cost tracking, and sessions.
    
    This class is the core of the LLM Gateway. It can be used:
      - As a standalone server (with Flask proxy)
      - Embedded in an IDE plugin (pure Python, no server needed)
      - As a library for other applications
    """

    def __init__(self, db_path: Optional[str] = None):
        self.router = AccountRouter()
        self.tracker = BalanceTracker(self.router)
        self.token_counter = TokenCounter(self.router)
        self.session_manager = SessionManager(self.router)

        # Initialize database (optional - can be in-memory only)
        self.db_path = db_path or os.path.join(os.path.dirname(__file__), "gateway.db")
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database."""
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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS budget_limits (
                account_id TEXT PRIMARY KEY,
                limit_usd REAL NOT NULL DEFAULT 0.0,
                updated_at TEXT NOT NULL
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

    def start_session(self, session_id: Optional[str] = None) -> str:
        """Start a new conversation session."""
        session_id = session_id or str(time.time_ns())

        # Reinitialize router from database (for persistence)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts")
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            config = AccountConfig(
                id=row[0], name=row[1], api_key=row[2],
                base_url=row[3] or "https://api.anthropic.com",
                model=row[4] or "claude-3-5-sonnet-20241022",
                max_tokens=row[5] or 8192,
                weight=row[6], enabled=bool(row[7]),
                status=AccountStatus(row[8]),
                remaining_balance=row[9], tokens_used=row[10],
                total_cost_usd=row[11],
            )
            self.router.register_account(config)

        return session_id

    def complete(
        self,
        session_id: str,
        prompt: str,
        max_tokens: int = 4096,
        force_account: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a completion request through the gateway.
        
        Args:
            session_id: The session ID (for sticky routing).
            prompt: The user prompt.
            max_tokens: Maximum response tokens.
            force_account: If set, force use this account instead of routing.
            
        Returns:
            Response dict compatible with Anthropic Completions API format.
        """
        # Route the request
        decision = self.router.route_request(session_id, prompt, max_tokens=max_tokens)

        if not decision.account_id:
            return {
                "error": {
                    "type": "routing_error",
                    "message": f"Routing failed: {decision.reason}",
                },
            }

        account = self.router.accounts[decision.account_id]

        # In a real implementation, this would forward to the actual Claude API
        # For now, return a mock response (useful for plugin testing)
        result = {
            "id": f"{account.id}-cm-{time.time_ns()}",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"[ROUTED TO {account.name}] Model: {account.model} | "
                        f"Cost estimate: ${self.token_counter.estimate_cost(
                            account.model, 128, 64):.6f}"
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
            "cost": self.token_counter.estimate_cost(account.model, 128, 64),
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

    def _log_request(
        self,
        session_id: str,
        account_id: str,
        prompt: str,
        response: Dict[str, Any],
    ) -> None:
        """Log a request for auditing."""
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


if __name__ == "__main__":
    # Demo
    gateway = LLMGateway()

    # Register some accounts
    gateway.register_account(AccountConfig(
        id="acc-alpha", name="Team Alpha", api_key="sk-test-alpha",
        remaining_balance=100.0, model="claude-3-5-sonnet"
    ))
    gateway.register_account(AccountConfig(
        id="acc-beta", name="Team Beta", api_key="sk-test-beta",
        remaining_balance=40.0, model="claude-3-haiku"
    ))

    # Test routing
    result = gateway.complete("What is the capital of France?", max_tokens=100)
    print(json.dumps(result, indent=2))

    print("\n--- Virtual Pool ---")
    print(json.dumps(gateway.get_virtual_pool(), indent=2))
