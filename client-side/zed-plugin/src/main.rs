//! LLM Gateway - Zed Plugin
//!
//! A Zed plugin that provides balance-aware routing across multiple LLM accounts.
//!
//! Features:
//!   - Multi-account pool with automatic failover
//!   - Cost-aware model selection (Claude, Codex, Ollama, etc.)
//!   - Per-account budget limits with warnings
//!   - Virtual pool balance tracking
//!   - Routing decision visibility in the UI
//!
//! Usage:
//!   1. Build the plugin: `cargo build --release`
//!   2. Copy to Zed's plugins directory: ~/.local/share/zed/plugins/llm-gateway/
//!   3. Configure accounts in Zed settings or via the plugin UI
//!   4. Set your custom model endpoint in Zed's settings.json:
//!      {
//!        "custom_models": [
//!          {
//!            "name": "llm-gateway",
//!            "endpoint": "http://localhost:8080/v1/messages/completions"
//!          }
//!        ],
//!        "default_model": "llm-gateway"
//!      }

use std::sync::{Arc, Mutex};
use zed::plugin::{Plugin, PluginContext};

// Re-export gateway types for convenience
mod gateway {
    pub use crate::gateway::{LLMGateway, AccountConfig, AccountStatus};
}

mod gateway {
    use serde_json::json;
    use crate::gateway::{AccountRouter, BalanceTracker, TokenCounter, LLMGateway, AccountConfig, AccountStatus};

    pub fn create_gateway() -> LLMGateway {
        let mut gateway = LLMGateway::new(None);

        // Default accounts - can be overridden via config
        let default_accounts = vec![
            AccountConfig {
                id: "default-1".to_string(),
                name: "Default Account".to_string(),
                api_key_hash: "hash-default-1".to_string(),
                base_url: "https://api.anthropic.com".to_string(),
                model: "claude-3-5-sonnet-20241022".to_string(),
                max_tokens: 8192,
                weight: 1.0,
                enabled: true,
                status: AccountStatus::Healthy,
                remaining_balance: 0.0,
                tokens_used: 0,
                total_cost_usd: 0.0,
                created_at: chrono::Utc::now(),
                last_used: None,
                budget_limit: 0.0,
            },
        ];

        for acc in default_accounts {
            gateway.register_account(acc);
        }

        gateway
    }

    pub fn register_account(gateway: &mut LLMGateway, config: AccountConfig) -> String {
        gateway.register_account(config)
    }

    pub fn unregister_account(gateway: &mut LLMGateway, account_id: &str) {
        gateway.unregister_account(account_id);
    }

    pub fn complete_request(
        gateway: &mut LLMGateway,
        session_id: &str,
        prompt: &str,
        max_tokens: u32,
    ) -> serde_json::Value {
        gateway.complete(session_id, prompt, max_tokens, None)
    }

    pub fn get_virtual_pool(gateway: &LLMGateway) -> serde_json::Value {
        gateway.get_virtual_pool()
    }

    pub fn get_account_stats(gateway: &LLMGateway, account_id: &str) -> Option<serde_json::Value> {
        gateway.get_account_stats(account_id)
    }

    pub fn get_all_accounts(gateway: &LLMGateway) -> Vec<serde_json::Value> {
        gateway.get_all_accounts()
    }
}

// ─── Plugin ────────────────────────────────────────────────────────────────

pub struct LLMGatewayPlugin;

impl Plugin for LLMGatewayPlugin {
    fn run(&self, _ctx: &PluginContext) -> zed::plugin::Result<()> {
        // This plugin runs as a background process.
        // We'll set up the gateway and provide an API for Zed to use.

        let mut gateway = gateway::create_gateway();

        // Log startup info
        eprintln!("[LLM Gateway Plugin] Started successfully");
        eprintln!("[LLM Gateway Plugin] Virtual pool balance: {}",
            gateway.get_virtual_pool()["balance_usd"].as_f64().unwrap_or(0.0));

        Ok(())
    }

    fn register_actions(&self, actions: &mut zed::plugin::ActionRegistry) {
        // Register plugin actions
        actions.register("llm-gateway/add-account", |event| {
            if let Some(name) = event.data().get::<String>("name") {
                eprintln!("[LLM Gateway Plugin] Add account: {}", name);
                // In a real implementation, we'd parse the full config from event data
            }
            Ok(())
        });

        actions.register("llm-gateway/set-budget", |event| {
            if let Some(account_id) = event.data().get::<String>("account_id") {
                if let Some(limit) = event.data().get::<f64>("limit_usd") {
                    eprintln!("[LLM Gateway Plugin] Set budget for {}: ${:.2}",
                        account_id, limit);
                }
            }
            Ok(())
        });

        actions.register("llm-gateway/show-pool", |event| {
            eprintln!("[LLM Gateway Plugin] Showing pool info");
            Ok(())
        });
    }
}
