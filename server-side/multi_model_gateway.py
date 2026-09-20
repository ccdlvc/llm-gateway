"""
Multi-Model LLM Gateway (Server-Side).

Routes requests between multiple models (Claude, Codex, Llama, etc.)
based on:
  - Cost optimization
  - Task type detection
  - Model availability
  - Budget constraints
"""

import sys
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(__file__[:-1]))

from gateway import LLMGateway, AccountConfig, AccountStatus


@dataclass
class ModelConfig:
    """Configuration for a single model provider."""
    name: str
    endpoint: str
    api_key: str
    model_name: str  # e.g., "claude-3-5-sonnet", "codex-coder"
    cost_per_token_input: float
    cost_per_token_output: float
    context_window: int
    max_tokens: int
    enabled: bool = True
    weight: float = 1.0
    description: str = ""


@dataclass
class ModelRoute:
    """A route from a task type to a model."""
    task_type: str
    model_name: str
    priority: int  # Higher = preferred
    fallback_to: Optional[str] = None  # Fallback model if primary unavailable


class MultiModelGateway(LLMGateway):
    """
    Gateway that supports multiple model providers in a single session.
    
    Supports:
      - Claude (Anthropic)
      - Codex / Code Llama
      - Other LLMs via any Anthropic-compatible API
    
    Routing strategy:
      1. Detect task type from prompt
      2. Match to best model for that task
      3. Apply cost-aware routing within each model's accounts
      4. Fall back to other models if the primary is unavailable
    """

    def __init__(self, db_path: Optional[str] = None):
        super().__init__(db_path)
        self.models: Dict[str, ModelConfig] = {}
        self.model_router: Dict[str, "LLMGateway"] = {}  # Per-model router
        self.session_configs: Dict[str, List[Dict]] = {}  # Session -> model config

    def register_model(self, config: ModelConfig) -> None:
        """Register a new model provider."""
        self.models[config.name] = config
        # Create a sub-gateway for this model's accounts
        self.model_router[config.name] = LLMGateway()

        # If it's an Anthropic-compatible endpoint, register accounts there
        if "anthropic" in config.endpoint.lower() or "claude" in config.endpoint.lower():
            self._register_anthropic_accounts(config)

    def _register_anthropic_accounts(self, config: ModelConfig) -> None:
        """Register Claude accounts under this model's router."""
        # In production, these would come from a config file / secrets manager
        # For demo, we'll register sample accounts
        accounts = [
            AccountConfig(
                id=f"{config.name}-acc-1",
                name="Claude-3.5-Pool-A",
                api_key=config.api_key,
                base_url=config.endpoint,
                model=config.model_name,
                weight=config.weight,
                remaining_balance=100.0,
            )
        ]
        for acc in accounts:
            self.model_router[config.name].register_account(acc)

    def _detect_task_type(self, prompt: str) -> str:
        """
        Detect what type of task the user wants to perform.
        
        Returns one of: 'code_generation', 'reasoning', 'creative_writing', 'general_chat'
        """
        prompt_lower = prompt.lower()

        # Code-related tasks → Codex/Code Llama
        code_keywords = [
            "function", "def ", "class ", "import ", "async def",
            "react", "vue", "typescript", "python", "java", "rust",
            "sql", "prisma", "docker", "kubernetes", "terraform", "git",
            "npm", "yarn", "package.json", "setup.py", "cargo.toml",
        ]
        if any(kw in prompt_lower for kw in code_keywords):
            return "code_generation"

        # Reasoning / math
        reasoning_keywords = [
            "prove", "calculate", "solve", "theorem", "integral",
            "derivative", "matrix", "probability", "expected value",
            "optimization", "algorithm", "complexity", "big-o",
        ]
        if any(kw in prompt_lower for kw in reasoning_keywords):
            return "reasoning"

        # Creative writing
        creative_keywords = [
            "story", "poem", "essay", "novel", "character",
            "script", "screenplay", "dialogue", "fiction",
        ]
        if any(kw in prompt_lower for kw in creative_keywords):
            return "creative_writing"

        # General chat
        return "general_chat"

    def _get_best_model_for_task(self, task_type: str) -> Optional[str]:
        """Get the best model name for a given task type."""
        task_model_map = {
            "code_generation": "codex",
            "reasoning": "claude-3.5",
            "creative_writing": "claude-3.5",
            "general_chat": "claude-haiku",  # cheapest for general tasks
        }
        return task_model_map.get(task_type, "claude-3.5")

    def complete(
        self,
        session_id: str,
        prompt: str,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Route a completion request to the best model for the task.
        
        Args:
            session_id: Session ID for sticky routing
            prompt: User prompt
            max_tokens: Maximum response tokens
            system_prompt: Optional system message
            
        Returns:
            Response dict (Anthropic-compatible format)
        """
        # Detect task type
        task_type = self._detect_task_type(prompt)
        
        # Determine which model to use
        best_model_name = self._get_best_model_for_task(task_type)

        # Get the model config
        model_config = self.models.get(best_model_name)
        if not model_config or not model_config.enabled:
            # Fallback: try Claude as default
            model_config = next(
                (m for m in self.models.values() if "claude" in m.name.lower()),
                None,
            )
            if not model_config:
                return {
                    "error": {
                        "type": "no_available_model",
                        "message": "No available models configured.",
                    }
                }

        # Get the model's account router
        model_router = self.model_router.get(best_model_name)
        if not model_router:
            return {
                "error": {
                    "type": "model_unavailable",
                    "message": f"Model '{best_model_name}' is not configured.",
                }
            }

        # Route within that model's accounts
        routing_decision = model_router.router.route_request(session_id, prompt)

        if not routing_decision.account_id:
            return {
                "error": {
                    "type": "no_accounts_available",
                    "message": f"No healthy accounts for model '{best_model_name}'.",
                }
            }

        # Get the actual API key and endpoint for this account
        account = model_router.router.accounts[routing_decision.account_id]

        # In a real implementation, you'd forward to the actual endpoint
        # For demo, we return a mock response
        cost_estimate = (
            128 * model_config.cost_per_token_input +
            64 * model_config.cost_per_token_output
        )

        response_content = f"[ROUTED TO {model_config.name.upper()} via {account.name}] " \
                          f"Task type: {task_type} → {best_model_name}"

        result = {
            "id": f"{best_model_name}-msg-{time.time_ns()}",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": response_content,
                }
            ],
            "model": model_config.model_name,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 128,
                "output_tokens": 64,
            },
            "cost": round(cost_estimate, 6),
        }

        # Record usage
        model_router.router.update_request_result(routing_decision.account_id, result)

        return result

    def get_model_info(self) -> List[Dict[str, Any]]:
        """Get information about all registered models."""
        return [
            {
                "name": m.name,
                "model": m.model_name,
                "endpoint": m.endpoint,
                "enabled": m.enabled,
                "description": m.description,
            }
            for m in self.models.values()
        ]


# ─── Demo ───────────────────────────────────────────────────────────────────

def demo_multi_model():
    """Demonstrate multi-model routing."""
    print("=" * 60)
    print("MULTI-MODEL GATEWAY DEMO")
    print("=" * 60)

    gateway = MultiModelGateway()

    # Register Claude-3.5 (general tasks)
    claude_config = ModelConfig(
        name="claude-3.5",
        endpoint="https://api.anthropic.com/v1/messages",
        api_key="sk-anthropic-key",
        model_name="claude-3-5-sonnet-20241022",
        cost_per_token_input=3e-6,    # $3/M tokens input
        cost_per_token_output=15e-6,  # $15/M tokens output
        context_window=200000,
        max_tokens=8192,
        enabled=True,
        weight=1.0,
        description="General purpose, high-quality responses",
    )
    gateway.register_model(claude_config)

    # Register Codex (code tasks)
    codex_config = ModelConfig(
        name="codex",
        endpoint="https://api.codex.ai/v1/completions",
        api_key="sk-codex-key",
        model_name="codex-coder-7b",
        cost_per_token_input=0.1e-6,  # Very cheap!
        cost_per_token_output=0.2e-6,
        context_window=4096,
        max_tokens=2048,
        enabled=True,
        weight=2.0,  # Higher weight = preferred for code tasks
        description="Code generation specialist",
    )
    gateway.register_model(codex_config)

    # Register Claude-3-Haiku (cheap general tasks)
    haiku_config = ModelConfig(
        name="claude-haiku",
        endpoint="https://api.anthropic.com/v1/messages",
        api_key="sk-anthropic-key",
        model_name="claude-3-haiku-20240307",
        cost_per_token_input=0.25e-6,  # $0.25/M input
        cost_per_token_output=1.25e-6,  # $1.25/M output
        context_window=200000,
        max_tokens=8192,
        enabled=True,
        weight=1.0,
        description="Cheap general chat",
    )
    gateway.register_model(haiku_config)

    session_id = "multi-session-1"
    gateway.start_session(session_id)

    # Test 1: Code generation → Codex
    print("\n--- Request 1: Write a Python function ---")
    prompt = "Write a Python function to compute fibonacci(n)"
    result = gateway.complete(session_id, prompt)
    print(f"Model used: {result.get('model', 'N/A')}")
    print(f"Cost: ${result.get('cost', 0):.6f}")

    # Test 2: Reasoning → Claude-3.5
    print("\n--- Request 2: Math reasoning ---")
    prompt = "Prove that the sum of two even numbers is even."
    result = gateway.complete(session_id, prompt)
    print(f"Model used: {result.get('model', 'N/A')}")

    # Test 3: Creative writing → Claude-3.5
    print("\n--- Request 3: Write a short story ---")
    prompt = "Write a short story about a robot who learns to paint."
    result = gateway.complete(session_id, prompt)
    print(f"Model used: {result.get('model', 'N/A')}")

    # Test 4: General chat → Claude-Haiku (cheapest)
    print("\n--- Request 4: General chat ---")
    prompt = "Tell me a joke about programmers."
    result = gateway.complete(session_id, prompt)
    print(f"Model used: {result.get('model', 'N/A')}")

    # Test 5: Code again → still Codex (sticky within task type)
    print("\n--- Request 5: Another code request ---")
    prompt = "Write a React component for a button with loading state."
    result = gateway.complete(session_id, prompt)
    print(f"Model used: {result.get('model', 'N/A')}")

    # Show routing summary
    print("\n--- Routing Summary ---")
    for model_name in gateway.models:
        model_router = gateway.model_router[model_name]
        stats = model_router.router.get_account_stats(model_router.router.accounts["acc-1"].id) if model_router.router.accounts else None
        if stats:
            print(f"  {model_name}: {stats['name']} - Balance: ${stats['remaining_balance']:.2f}")


if __name__ == "__main__":
    demo_multi_model()
