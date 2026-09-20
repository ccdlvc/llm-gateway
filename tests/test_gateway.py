"""Tests for the LLM Gateway."""

import sys
sys.path.insert(0, str(__file__[:-5]))

from gateway import (
    LLMGateway,
    AccountConfig,
    AccountStatus,
)


def test_register_account():
    """Test registering an account."""
    gateway = LLMGateway()
    config = AccountConfig(
        id="test-acc",
        name="Test Account",
        api_key="sk-test-key",
        weight=1.0,
        remaining_balance=100.0,
    )
    account_id = gateway.register_account(config)
    assert account_id == "test-acc"


def test_unregister_account():
    """Test unregistering an account."""
    gateway = LLMGateway()
    config = AccountConfig(
        id="test-acc",
        name="Test Account",
        api_key="sk-test-key",
    )
    gateway.register_account(config)
    assert "test-acc" in gateway.router.accounts

    gateway.unregister_account("test-acc")
    assert "test-acc" not in gateway.router.accounts


def test_virtual_pool():
    """Test virtual pool balance calculation."""
    gateway = LLMGateway()

    accounts = [
        AccountConfig(id="a", name="A", api_key="sk-a", remaining_balance=100.0),
        AccountConfig(id="b", name="B", api_key="sk-b", remaining_balance=50.0),
        AccountConfig(id="c", name="C", api_key="sk-c", remaining_balance=150.0),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    pool = gateway.get_virtual_pool()
    assert pool["balance_usd"] == 300.0
    assert pool["tokens_available"] == 20_000_000_000  # ~$0.015/M tokens


def test_routing_basic():
    """Test basic routing picks highest balance account."""
    gateway = LLMGateway()

    accounts = [
        AccountConfig(id="acc-1", name="A", api_key="sk-a", remaining_balance=100.0),
        AccountConfig(id="acc-2", name="B", api_key="sk-b", remaining_balance=40.0),
        AccountConfig(id="acc-3", name="C", api_key="sk-c", remaining_balance=160.0),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    session_id = "sess-1"
    gateway.start_session(session_id)

    # First request should go to the account with most balance (acc-3)
    result = gateway.complete(session_id, "Hello")
    assert "acc-3" in result["id"] or "Team Gamma" in result.get("model", "")


def test_routing_weighted():
    """Test weighted routing."""
    gateway = LLMGateway()

    accounts = [
        AccountConfig(id="acc-1", name="A", api_key="sk-a", weight=3.0, remaining_balance=50.0),
        AccountConfig(id="acc-2", name="B", api_key="sk-b", weight=1.0, remaining_balance=50.0),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    session_id = "sess-weighted"
    gateway.start_session(session_id)

    # Account A has higher weight, so should be preferred
    result = gateway.complete(session_id, "Hello")
    assert "acc-1" in result["id"]


def test_sticky_session():
    """Test that sticky sessions stay on the same account."""
    gateway = LLMGateway()

    accounts = [
        AccountConfig(id="acc-1", name="A", api_key="sk-a", remaining_balance=100.0),
        AccountConfig(id="acc-2", name="B", api_key="sk-b", remaining_balance=100.0),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    session_id = "sess-sticky"
    gateway.start_session(session_id)

    # First request
    result1 = gateway.complete(session_id, "First prompt")
    first_model = result1.get("model", "")

    # Second request should use the same account (sticky)
    result2 = gateway.complete(session_id, "Second prompt")
    second_model = result2.get("model", "")

    assert first_model == second_model


def test_fallback_on_exhaustion():
    """Test fallback when an account is exhausted."""
    gateway = LLMGateway()

    accounts = [
        AccountConfig(id="acc-1", name="A", api_key="sk-a", remaining_balance=0.0),
        AccountConfig(id="acc-2", name="B", api_key="sk-b", remaining_balance=100.0),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    session_id = "sess-fallback"
    gateway.start_session(session_id)

    # First request goes to acc-2 (only healthy one)
    result = gateway.complete(session_id, "Hello")
    assert "acc-2" in result["id"]


def test_fallback_on_rate_limit():
    """Test fallback when an account is rate limited."""
    gateway = LLMGateway()

    accounts = [
        AccountConfig(id="acc-1", name="A", api_key="sk-a", remaining_balance=100.0),
        AccountConfig(id="acc-2", name="B", api_key="sk-b", remaining_balance=100.0),
    ]

    for acc in accounts:
        gateway.register_account(acc)

    session_id = "sess-rate-limit"
    gateway.start_session(session_id)

    # Simulate rate limiting on acc-1
    gateway.router.accounts["acc-1"].status = AccountStatus.RATE_LIMITED

    result = gateway.complete(session_id, "Hello")
    assert "acc-2" in result["id"]


def test_cost_tracking():
    """Test that costs are tracked per account."""
    gateway = LLMGateway()

    config = AccountConfig(id="acc-1", name="A", api_key="sk-a", remaining_balance=100.0)
    gateway.register_account(config)

    session_id = "sess-cost"
    gateway.start_session(session_id)

    for i in range(5):
        gateway.complete(session_id, f"Prompt {i}")

    stats = gateway.get_account_stats("acc-1")
    assert stats["total_cost_usd"] > 0


def test_database_persistence():
    """Test that data persists to the database."""
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")

        gateway = LLMGateway(db_path=db_path)

        config = AccountConfig(id="db-acc", name="DB Account", api_key="sk-db", remaining_balance=50.0)
        gateway.register_account(config)

        # Verify it's in the database
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM accounts")
        count = cursor.fetchone()[0]
        assert count == 1
        conn.close()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
