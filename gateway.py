"""
LLM Account Gateway - Balance-aware routing for multi-account Claude usage.

Architecture:
┌──────────────────┐
│  Claude Code     │  →  proxy /api/v1/completions (or Anthropic-compatible)
│  (intercepted)   │      ↓
└────────┬─────────┘   ┌──────┬────────┬────────┐
         │             │      │         │        │
         ▼             ▼      ▼         ▼        ▼
  ┌──────────────────┐│  ┌────────┐│  ┌────────┐│  ┌────────┐
  │  Account Router   ││  │Account A││  │Account B││  │Account C│
  │                   ││  │(70%)    ││  │(35%)    ││  │(90%)    │
  │  - Weighted       ││  │         ││  │         ││  │         │
  │    scoring        ││  │         ││  │         ││  │         │
  │  - Sticky session ││  │         ││  │         ││  │         │
  └────────┬─────────┘│  └─────────┘│  └─────────┘│  └─────────┘
           │           │             │             │
           ▼           ▼             ▼             ▼
    ┌──────────────────┐   ┌────────┐   ┌────────┐   ┌────────┐
    │ Claude API A     │   │ Claude │   │ Claude │   │ Claude │
    │                  │   │ API B  │   │ API C  │   │ API D  │
    └──────────────────┘   └────────┘   └────────┘   └────────┘

Key components:
- AccountRouter: weighted routing + sticky sessions
- TokenCounter: tracks token usage per account
- BalanceTracker: monitors budget and health
- VirtualPool: unified abstraction presenting single balance to client
- SessionManager: maintains conversation state across account boundaries
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
import sqlite3
import hashlib


# ─── Enums & Constants ──────────────────────────────────────────────────────

class AccountStatus(Enum):
    HEALTHY = "healthy"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    UNAVAILABLE = "unavailable"
    MAINTENANCE = "maintenance"


class RoutingStrategy(Enum):
    BALANCE_AWARE = "balance_aware"       # Route to account with most remaining balance
    ROUND_ROBIN = "round_robin"           # Even distribution
    WEIGHTED = "weighted"                 # Score-based routing
    STICKY = "sticky"                     # Stick to same account per session


@dataclass
class AccountConfig:
    """Configuration for a single Claude API account."""
    id: str
    name: str
    api_key: str
    base_url: str = "https://api.anthropic.com"
    model: str = "claude-3-5-sonnet-20241022"
    max_tokens: int = 8192
    max_retry_attempts: int = 3
    rate_limit_window: int = 60  # seconds
    max_requests_per_window: int = 100
    enabled: bool = True
    weight: float = 1.0  # Higher weight = more likely to be chosen
    description: str = ""


@dataclass
class SessionState:
    """Per-session state for sticky routing."""
    session_id: str
    started_at: float
    messages: List[Dict[str, Any]] = field(default_factory=list)
    current_account_id: Optional[str] = None
    last_account_switch: Optional[float] = None
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0


@dataclass
class RoutingDecision:
    """Result of a routing decision."""
    account_id: str
    account_name: str
    score: float
    reason: str
    fallback_accounts: List[str]
    timestamp: float


# ─── Account Router ─────────────────────────────────────────────────────────

class AccountRouter:
    """
    Intelligent account router with sticky sessions and weighted scoring.
    
    Routing Algorithm:
        1. Determine if sticky session applies
        2. If sticky → use current account unless exhausted/unavailable
        3. Otherwise, compute scores for all healthy accounts:
           score = balance × weight × health_factor × (1 - rate_limit_penalty) × latency_factor
        4. Select top N accounts and route to highest-scored one
    """

    def __init__(self):
        self.accounts: Dict[str, AccountConfig] = {}
        self.sessions: Dict[str, SessionState] = {}
        self.token_counters: Dict[str, int] = defaultdict(int)
        self.cost_trackers: Dict[str, float] = defaultdict(float)
        self.request_counts: Dict[str, List[float]] = defaultdict(list)  # For rate limiting
        self.latency_history: Dict[str, List[float]] = defaultdict(list)
        self._lock = None  # Would use threading.Lock in multi-threaded version

    def register_account(self, config: AccountConfig) -> None:
        """Register a new account."""
        self.accounts[config.id] = config

    def unregister_account(self, account_id: str) -> None:
        """Unregister an account."""
        if account_id in self.accounts:
            del self.accounts[account_id]

    def _compute_score(self, account_id: str) -> float:
        """
        Compute routing score for an account.
        
        Score = base_balance × weight × health_factor × rate_limit_factor × latency_factor
        """
        account = self.accounts[account_id]
        if not account.enabled:
            return 0.0

        # Base: remaining balance relative to total pool
        total_balance = sum(
            a.remaining_balance for a in self.accounts.values()
            if a.enabled and a.status == AccountStatus.HEALTHY
        )
        if total_balance == 0:
            return 0.0

        base_score = account.remaining_balance / total_balance * account.weight

        # Health factor (penalize unhealthy accounts)
        health_factor = {
            AccountStatus.HEALTHY: 1.0,
            AccountStatus.RATE_LIMITED: 0.3,
            AccountStatus.QUOTA_EXHAUSTED: 0.0,
            AccountStatus.UNAVAILABLE: 0.0,
            AccountStatus.MAINTENANCE: 0.5,
        }[account.status]

        # Rate limit factor
        rate_limit_factor = self._compute_rate_limit_factor(account_id)

        # Latency factor (penalize slow accounts)
        latency_factor = self._compute_latency_factor(account_id)

        return base_score * health_factor * rate_limit_factor * latency_factor

    def _compute_rate_limit_factor(self, account_id: str) -> float:
        """Compute rate limit penalty factor."""
        account = self.accounts[account_id]
        now = time.time()
        window_start = now - account.rate_limit_window

        # Count requests in the current window
        recent_requests = [
            t for t in self.request_counts[account_id]
            if t > window_start
        ]

        remaining_capacity = account.max_requests_per_window - len(recent_requests)
        return min(1.0, remaining_capacity / account.max_requests_per_window)

    def _compute_latency_factor(self, account_id: str) -> float:
        """Compute latency factor based on recent response times."""
        account = self.accounts[account_id]
        history = self.latency_history.get(account_id, [])

        if len(history) < 3:
            return 1.0  # Not enough data yet

        avg_latency = sum(history) / len(history)
        # Penalize accounts with high latency (assume > 2s is bad)
        penalty = max(0, (avg_latency - 1.0) / 2.0)  # Penalty starts at 2s
        return max(0.5, 1.0 - penalty)

    def _get_current_session(self, session_id: str) -> Optional[SessionState]:
        """Get or create session state."""
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(
                session_id=session_id,
                started_at=time.time(),
            )
        return self.sessions[session_id]

    def _is_sticky_session(self, session_id: str) -> bool:
        """Check if this is a sticky session (not just a one-off request)."""
        session = self._get_current_session(session_id)
        # Sticky sessions are those with multiple messages
        return len(session.messages) > 0

    def route_request(
        self,
        session_id: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> RoutingDecision:
        """
        Determine which account to route a request to.
        
        Decision logic:
          1. If sticky session and current account is healthy → use it
          2. Otherwise, score all accounts and pick the best
          3. Fall back to any available account if primary is exhausted
        """
        now = time.time()

        # Update session state
        session = self._get_current_session(session_id)
        session.messages.append({"role": "user", "content": prompt})

        # Check sticky session: prefer current account unless it's unhealthy
        if session.current_account_id and self.accounts[session.current_account_id].enabled:
            primary_account = session.current_account_id
            primary_config = self.accounts[primary_account]

            # Skip if this account is exhausted or unavailable
            if (primary_config.remaining_balance <= 0
                    or primary_config.status != AccountStatus.HEALTHY):
                session.current_account_id = None
            else:
                # Use sticky session's current account
                score = self._compute_score(primary_account)
                return RoutingDecision(
                    account_id=primary_account,
                    account_name=self.accounts[primary_account].name,
                    score=score,
                    reason=f"sticky_session: {self.accounts[primary_account].name}",
                    fallback_accounts=[],
                    timestamp=now,
                )

        # No sticky session or no active account → compute scores
        healthy_accounts = [
            (aid, acc) for aid, acc in self.accounts.items()
            if acc.enabled and acc.status == AccountStatus.HEALTHY
        ]

        if not healthy_accounts:
            return RoutingDecision(
                account_id=None,
                account_name="none",
                score=0.0,
                reason="no_healthy_accounts",
                fallback_accounts=[],
                timestamp=now,
            )

        # Score all healthy accounts
        scored = [(aid, self._compute_score(aid)) for aid, _ in healthy_accounts]

        # Sort by score descending
        scored.sort(key=lambda x: -x[1])

        # Pick top account
        best_account_id, best_score = scored[0]
        best_account = self.accounts[best_account_id]

        # Determine reason
        if best_account_id == session.current_account_id:
            reason = f"sticky_session: {best_account.name}"
        else:
            reason = (f"balance_aware: {best_account.name} "
                      f"(score={best_score:.4f})")

        # Determine fallbacks (accounts with non-zero balance)
        fallbacks = [aid for aid, _ in scored[1:] if self.accounts[aid].remaining_balance > 0]

        return RoutingDecision(
            account_id=best_account_id,
            account_name=best_account.name,
            score=best_score,
            reason=reason,
            fallback_accounts=fallbacks,
            timestamp=now,
        )

    def update_request_result(self, account_id: str, result: Dict[str, Any]) -> None:
        """Update tracking after a request completes."""
        account = self.accounts[account_id]

        # Track token usage
        tokens_used = result.get("usage", {}).get("input_tokens", 0) + \
                      result.get("usage", {}).get("output_tokens", 0)
        self.token_counters[account_id] += tokens_used

        # Track cost
        cost = result.get("cost", 0.0)
        self.cost_trackers[account_id] += cost

        # Track latency
        total_time = result.get("total_time_ms", 0) / 1000.0  # convert to seconds
        self.latency_history[account_id].append(total_time)
        # Keep only last 100 samples
        if len(self.latency_history[account_id]) > 100:
            self.latency_history[account_id] = \
                self.latency_history[account_id][-100:]

        # Track rate limiting
        now = time.time()
        self.request_counts[account_id].append(now)
        if len(self.request_counts[account_id]) > account.max_requests_per_window:
            self.request_counts[account_id] = \
                self.request_counts[account_id][-account.max_requests_per_window:]

        # Update status based on result
        if "error" in result:
            error_type = result["error"].get("type", "")
            if "rate_limit" in error_type.lower():
                account.status = AccountStatus.RATE_LIMITED
            elif "quota" in error_type.lower() or "budget" in error_type.lower():
                account.status = AccountStatus.QUOTA_EXHAUSTED
            elif "unavailable" in error_type.lower():
                account.status = AccountStatus.UNAVAILABLE

        # Update remaining balance (simplified: assume $0.015 / 1M tokens for demo)
        # In production, fetch from actual API or use a billing webhook
        # For now, we'll use a fixed rate that can be configured
        tokens_per_dollar = 1_000_000 / 0.015  # ~66.7M tokens per $1
        remaining = (account.remaining_balance - cost) * tokens_per_dollar
        account.remaining_balance = remaining

    def get_account_stats(self, account_id: str) -> Dict[str, Any]:
        """Get stats for an account."""
        if account_id not in self.accounts:
            return {}
        account = self.accounts[account_id]
        return {
            "id": account.id,
            "name": account.name,
            "status": account.status.value,
            "remaining_balance": account.remaining_balance,
            "tokens_used": self.token_counters[account_id],
            "total_cost_usd": round(self.cost_trackers[account_id], 4),
            "requests_in_window": len(self.request_counts[account_id]),
        }

    def get_virtual_pool_stats(self) -> Dict[str, Any]:
        """Get virtual pool statistics (unified view)."""
        total_balance = sum(
            a.remaining_balance for a in self.accounts.values()
            if a.enabled and a.status == AccountStatus.HEALTHY
        )
        total_tokens_available = sum(
            (a.remaining_balance or 0) * 66_666_667  # ~$0.015/M tokens
            for a in self.accounts.values()
            if a.enabled and a.status == AccountStatus.HEALTHY
        )

        total_tokens_used = sum(self.token_counters.values())
        total_cost = sum(self.cost_trackers.values())

        return {
            "total_balance_usd": round(total_balance, 2),
            "tokens_available": int(total_tokens_available),
            "tokens_used": total_tokens_used,
            "total_cost_usd": round(total_cost, 4),
            "accounts_count": len(self.accounts),
            "healthy_accounts": sum(
                1 for a in self.accounts.values()
                if a.status == AccountStatus.HEALTHY
            ),
        }


# ─── Balance Tracker ─────────────────────────────────────────────────────────

class BalanceTracker:
    """
    Tracks balance and budget across accounts.
    
    Supports:
      - Per-account budget limits
      - Virtual pool with unified balance view
      - Budget alerts and notifications
    """

    def __init__(self, account_router: AccountRouter):
        self.router = account_router
        self.budget_limits: Dict[str, float] = {}  # account_id -> max budget

    def set_budget_limit(self, account_id: str, limit_usd: float) -> None:
        """Set a per-account budget limit."""
        self.budget_limits[account_id] = limit_usd

    def get_remaining_budget(self, account_id: str) -> float:
        """Get remaining budget for an account (respects limit)."""
        config = self.router.accounts.get(account_id)
        if not config:
            return 0.0

        # Track spent amount
        total_spent = sum(self.router.cost_trackers.get(account_id, 0))

        # Apply limit
        limit = self.budget_limits.get(account_id, float('inf'))
        remaining = min(config.remaining_balance, limit - total_spent)

        return max(0.0, remaining)

    def get_virtual_pool_balance(self) -> Dict[str, Any]:
        """Get the virtual pool balance (sum of all healthy accounts)."""
        stats = self.router.get_virtual_pool_stats()
        # Filter to only healthy accounts with budget not exhausted
        healthy_balance = sum(
            a.remaining_balance for a in self.router.accounts.values()
            if a.enabled and a.status == AccountStatus.HEALTHY
        )
        return {
            **stats,
            "virtual_pool_balance": round(healthy_balance, 2),
        }

    def check_budget_exhausted(self, account_id: str) -> bool:
        """Check if an account's budget is exhausted."""
        remaining = self.get_remaining_budget(account_id)
        return remaining <= 0.0


# ─── Token Counter ──────────────────────────────────────────────────────────

class TokenCounter:
    """Tracks token usage across accounts for fair distribution."""

    def __init__(self, account_router: AccountRouter):
        self.router = account_router
        self.tokens_per_dollar: float = 66_666_667  # ~$0.015 per M tokens

    def estimate_cost(self, prompt: str, max_tokens: int) -> Tuple[int, float]:
        """Estimate tokens and cost for a prompt."""
        # Simple estimation: assume avg input is ~20% of output
        estimated_input = len(prompt)  # rough estimate (characters)
        estimated_output = max_tokens * 0.8  # model produces ~80% of max
        total_tokens = estimated_input + estimated_output

        # Cost estimation
        cost_per_token = 0.015 / self.tokens_per_dollar  # $0.015 per M tokens
        estimated_cost = total_tokens * cost_per_token

        return total_tokens, estimated_cost

    def record_usage(self, account_id: str, tokens_in: int, tokens_out: int) -> None:
        """Record token usage for an account."""
        self.router.token_counters[account_id] += (tokens_in + tokens_out)


# ─── Session Manager ────────────────────────────────────────────────────────

class SessionManager:
    """
    Manages conversation sessions across account boundaries.
    
    Ensures that conversation history is preserved when switching accounts,
    and that context is properly carried over.
    """

    def __init__(self, account_router: AccountRouter):
        self.router = account_router
        self.session_history: Dict[str, List[Dict]] = defaultdict(list)

    def add_message(self, session_id: str, message: Dict[str, Any]) -> None:
        """Add a message to the session history."""
        session = self._get_or_create_session(session_id)
        session.messages.append(message)
        self.session_history[session_id].append({
            "role": message.get("role", "user"),
            "content": message.get("content", ""),
            "timestamp": time.time(),
        })

    def get_session_context(self, session_id: str, max_messages: int = 20) -> List[Dict]:
        """Get recent messages from a session for context."""
        session = self._get_or_create_session(session_id)
        # Return most recent messages
        return session.messages[-max_messages:] if session.messages else []

    def _get_or_create_session(self, session_id: str) -> SessionState:
        """Get or create a session state."""
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(
                session_id=session_id,
                started_at=time.time(),
            )
        return self.sessions[session_id]

    @property
    def sessions(self) -> Dict[str, SessionState]:
        """Property to access sessions dict."""
        return self.router.sessions


# ─── Virtual Pool ────────────────────────────────────────────────────────────

class VirtualPool:
    """
    Presents multiple accounts as a single unified balance pool.
    
    Users see one "Claude Pool" with a single remaining balance,
    rather than individual account balances.
    """

    def __init__(self, account_router: AccountRouter):
        self.router = account_router

    def get_balance(self) -> Dict[str, Any]:
        """Get the virtual pool's unified balance view."""
        stats = self.router.get_virtual_pool_stats()
        return {
            "pool_name": "Claude Pool",
            "balance_usd": round(stats["total_balance_usd"], 2),
            "tokens_available": stats["tokens_available"],
            "tokens_used": stats["tokens_used"],
            "accounts": [
                {
                    "id": a.id,
                    "name": a.name,
                    "balance": round(a.remaining_balance, 2),
                    "status": a.status.value,
                }
                for a in self.router.accounts.values()
                if a.enabled
            ],
        }

    def get_allocation(self) -> Dict[str, float]:
        """Get the recommended allocation percentages per account."""
        stats = self.router.get_virtual_pool_stats()
        total_balance = stats["total_balance_usd"]
        if total_balance == 0:
            return {}

        allocations = {}
        for aid, acc in self.router.accounts.items():
            if acc.enabled and acc.status == AccountStatus.HEALTHY:
                balance = acc.remaining_balance
                weight = acc.weight
                # Weighted allocation
                score = balance * weight / total_balance * 100
                allocations[aid] = round(score, 2)

        return allocations


# ─── Retry Manager ──────────────────────────────────────────────────────────

class RetryManager:
    """Manages retries across accounts when one is rate-limited or unavailable."""

    def __init__(self, account_router: AccountRouter):
        self.router = account_router
        self.retry_history: Dict[str, List[Dict]] = defaultdict(list)

    def should_retry(self, account_id: str, attempt: int = 1) -> bool:
        """Determine if we should retry a failed request on another account."""
        account = self.router.accounts.get(account_id)
        if not account:
            return False

        # Don't retry if account is in bad state
        if account.status in (AccountStatus.QUOTA_EXHAUSTED, AccountStatus.UNAVAILABLE):
            return False

        # Don't retry too frequently (exponential backoff-ish)
        if attempt > 5:
            return False

        return True

    def select_fallback(self, primary_account_id: str) -> Optional[str]:
        """Select a fallback account when the primary fails."""
        # Find healthy accounts excluding the failed one
        candidates = [
            aid for aid, acc in self.router.accounts.items()
            if acc.enabled and acc.status == AccountStatus.HEALTHY
            and aid != primary_account_id
        ]

        if not candidates:
            return None

        # Pick the one with most remaining balance
        best = max(candidates, key=lambda aid: self.router.accounts[aid].remaining_balance)
        return best

    def record_failure(self, account_id: str, error: Dict[str, Any]) -> None:
        """Record a failure for retry logic."""
        self.retry_history[account_id].append({
            "error": error,
            "timestamp": time.time(),
        })


# ─── Main Gateway ───────────────────────────────────────────────────────────

class LLMGateway:
    """
    Main LLM Account Gateway.
    
    Exposes an API compatible with Anthropic's Completions API,
    routing requests through the account router.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.router = AccountRouter()
        self.tracker = BalanceTracker(self.router)
        self.token_counter = TokenCounter(self.router)
        self.session_manager = SessionManager(self.router)
        self.virtual_pool = VirtualPool(self.router)
        self.retry_manager = RetryManager(self.router)

        # Initialize database
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
                session_id TEXT,
                account_id TEXT,
                model TEXT,
                prompt TEXT,
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
        """Register a new account."""
        # Store hashed API key for security
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

        # Also register in memory
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
        session_id = session_id or str(uuid.uuid4())

        # Initialize virtual pool balance from database
        for row in sqlite3.connect(self.db_path).execute("SELECT * FROM accounts"):
            config = AccountConfig(
                id=row[0], name=row[1], api_key_hash=row[2],
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

    def complete(self, session_id: str, prompt: str, max_tokens: int = 4096) -> Dict[str, Any]:
        """
        Process a completion request through the gateway.
        
        Args:
            session_id: The session ID (for sticky routing).
            prompt: The user prompt.
            max_tokens: Maximum tokens for response.

        Returns:
            Response dict compatible with Anthropic Completions API format.
        """
        # Route the request
        decision = self.router.route_request(session_id, prompt, max_tokens=max_tokens)

        if not decision.account_id:
            return {
                "error": {
                    "type": "error",
                    "message": "No available accounts for routing.",
                },
            }

        account = self.router.accounts[decision.account_id]

        # In a real implementation, this would forward to the actual Claude API
        # For now, return a mock response
        result = {
            "id": f"{account.id}-cm-{uuid.uuid4().hex[:8]}",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": f"[ROUTED TO {account.name}] This is a mock response for prompt: {prompt[:50]}...",
                }
            ],
            "model": account.model,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 128,
                "output_tokens": 64,
            },
            "cost": 0.000128 * 0.015 + 0.000072 * 0.075,  # Mock cost
        }

        # Record the result
        self.router.update_request_result(decision.account_id, result)

        # Log the request
        self._log_request(
            session_id=session_id,
            account_id=decision.account_id,
            prompt=prompt,
            response=result,
            latency_ms=0.0,  # Would measure in real impl
        )

        return result

    def _log_request(self, session_id: str, account_id: str, prompt: str,
                     response: Dict, latency_ms: float) -> None:
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
            response.get("cost", 0.0), latency_ms, error,
            time.time(),
        ))

        conn.commit()
        conn.close()

    def get_account_stats(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Get stats for a specific account."""
        row = sqlite3.connect(self.db_path).execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()

        if not row:
            return None

        config = AccountConfig(
            id=row[0], name=row[1], api_key_hash=row[2],
            base_url=row[3] or "https://api.anthropic.com",
            model=row[4] or "claude-3-5-sonnet-20241022",
            max_tokens=row[5] or 8192,
            weight=row[6], enabled=bool(row[7]),
            status=AccountStatus(row[8]),
            remaining_balance=row[9], tokens_used=row[10],
            total_cost_usd=row[11],
        )

        return {
            "id": config.id,
            "name": config.name,
            "status": config.status.value,
            "remaining_balance": round(config.remaining_balance, 2),
            "tokens_used": config.tokens_used,
            "total_cost_usd": round(config.total_cost_usd, 4),
        }

    def get_virtual_pool(self) -> Dict[str, Any]:
        """Get the virtual pool view."""
        return self.virtual_pool.get_balance()


# ─── Demo / CLI ──────────────────────────────────────────────────────────────

def main():
    """Demo the gateway."""
    gateway = LLMGateway()

    # Register accounts
    accounts = [
        AccountConfig(id="acc-1", name="Team A - Claude 3.5", api_key="sk-...", weight=1.0),
        AccountConfig(id="acc-2", name="Team B - Claude 3.5", api_key="sk-...", weight=1.0),
        AccountConfig(id="acc-3", name="Team C - Claude 3.5", api_key="sk-...", weight=1.0),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    # Start a session
    session_id = gateway.start_session()

    print("=== Virtual Pool Balance ===")
    pool = gateway.get_virtual_pool()
    print(json.dumps(pool, indent=2))

    print("\n=== Simulating requests ===")
    for i in range(10):
        result = gateway.complete(session_id, f"Prompt {i+1}: Explain quantum computing")
        print(f"  Request {i+1} → {result['id']} (cost: ${result.get('cost', 0):.6f})")

    print("\n=== Updated Pool ===")
    pool = gateway.get_virtual_pool()
    print(json.dumps(pool, indent=2))


if __name__ == "__main__":
    main()
