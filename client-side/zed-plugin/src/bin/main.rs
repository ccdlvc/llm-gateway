//! LLM Gateway Plugin - Standalone Demo / Entry Point
//!
//! This binary can be run directly to demonstrate the gateway's functionality.
//! It also serves as a drop-in replacement for the Zed plugin when used via
//! the custom_models configuration in Zed.

use std::sync::{Arc, Mutex};
use std::time::Duration;

mod gateway;

fn main() {
    println!("╔══════════════════════════════════════════════════════╗");
    println!("║   LLM Gateway - Zed Plugin (Standalone Demo)        ║");
    println!("╚══════════════════════════════════════════════════════╝");

    let mut gateway = gateway::LLMGateway::new(None);

    // ─── Register Accounts ──────────────────────────────────────────────────

    let acc1 = gateway::AccountConfig {
        id: "acc-alpha".to_string(),
        name: "Team Alpha (Premium)".to_string(),
        api_key_hash: "hash-team-alpha".to_string(),
        base_url: "https://api.anthropic.com/v1/messages".to_string(),
        model: "claude-3-5-sonnet-20241022".to_string(),
        max_tokens: 8192,
        weight: 1.5,
        enabled: true,
        status: gateway::AccountStatus::Healthy,
        remaining_balance: 100.0,
        tokens_used: 0,
        total_cost_usd: 0.0,
        created_at: chrono::Utc::now(),
        last_used: None,
        budget_limit: 0.0,
    };

    let acc2 = gateway::AccountConfig {
        id: "acc-beta".to_string(),
        name: "Team Beta (Budget)".to_string(),
        api_key_hash: "hash-team-beta".to_string(),
        base_url: "https://api.anthropic.com/v1/messages".to_string(),
        model: "claude-3-haiku-20240307".to_string(),
        max_tokens: 8192,
        weight: 1.0,
        enabled: true,
        status: gateway::AccountStatus::Healthy,
        remaining_balance: 50.0,
        tokens_used: 0,
        total_cost_usd: 0.0,
        created_at: chrono::Utc::now(),
        last_used: None,
        budget_limit: 10.0, // $10 budget limit
    };

    let acc3 = gateway::AccountConfig {
        id: "acc-local".to_string(),
        name: "Local Ollama (Free)".to_string(),
        api_key_hash: "hash-local".to_string(),
        base_url: "http://localhost:11434/v1/chat/completions".to_string(),
        model: "codellama-7b".to_string(),
        max_tokens: 4096,
        weight: 2.0,
        enabled: true,
        status: gateway::AccountStatus::Healthy,
        remaining_balance: f64::INFINITY, // Unlimited (local model)
        tokens_used: 0,
        total_cost_usd: 0.0,
        created_at: chrono::Utc::now(),
        last_used: None,
        budget_limit: 0.0,
    };

    let _ = gateway.register_account(acc1);
    let _ = gateway.register_account(acc2);
    let _ = gateway.register_account(acc3);

    // ─── Show Virtual Pool ───────────────────────────────────────────────────

    println!("\n📊 Virtual Pool Balance:");
    let pool = gateway.get_virtual_pool();
    println!("   {}", serde_json::to_string_pretty(&pool).unwrap());

    // ─── Demo Routing ────────────────────────────────────────────────────────

    println!("\n🧪 Routing Demo:");
    println!("────────────────────────────────────────");

    let test_prompts = vec![
        ("What is the capital of France?", "general_chat"),
        ("Write a Python function to sort a list", "code_generation"),
        ("Explain quantum entanglement", "reasoning"),
        ("Write a short story about a robot", "creative_writing"),
        ("Debug this React component", "code_generation"),
    ];

    for (prompt, _) in &test_prompts {
        let result = gateway.complete(
            "demo-session",
            prompt,
            256,
            None,
        );
        println!("\n   Prompt: {}", prompt);
        println!("   Response: {}", result["content"][0]["text"].as_str().unwrap_or("N/A"));
    }

    // ─── Show Account Stats ───────────────────────────────────────────────────

    println!("\n📈 Account Stats:");
    let accounts = gateway.get_all_accounts();
    for acc in &accounts {
        println!("   {}", serde_json::to_string_pretty(acc).unwrap());
    }

    println!("\n✅ Demo complete!");
}
