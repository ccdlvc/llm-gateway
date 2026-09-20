//! Gateway core module - shared between plugin and standalone binary.
//!
//! This contains the core routing logic that powers both:
//! - The Zed plugin (when loaded as a plugin)
//! - The standalone demo binary

use std::sync::{Arc, Mutex};
use serde::{Deserialize, Serialize};

// ─── Enums and Data Structures ─────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AccountStatus {
    Healthy,
    RateLimited,
    Maintenance,
    Exhausted,
}

impl std::fmt::Display for AccountStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AccountStatus::Healthy => write!(f, "healthy"),
            AccountStatus::RateLimited => write!(f, "rate_limited"),
            AccountStatus::Maintenance => write!(f, "maintenance"),
            AccountStatus::Exhausted => write!(f, "exhausted"),
        }
    }
}

#[derive(Debug, Clone)]
pub struct AccountConfig {
    pub id: String,
    pub name: String,
    pub api_key_hash: String,
    pub base_url: String,
    pub model: String,
    pub max_tokens: u32,
    pub weight: f64,
    pub enabled: bool,
    pub status: AccountStatus,
    pub remaining_balance: f64,
    pub tokens_used: u64,
    pub total_cost_usd: f64,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub last_used: Option<chrono::DateTime<chrono::Utc>>,
    pub budget_limit: f64,
}

#[derive(Debug, Clone)]
pub struct SessionState {
    pub id: String,
    pub started_at: f64,
    pub current_account_id: Option<String>,
    pub total_tokens_used: u64,
    pub total_cost_usd: f64,
}

#[derive(Debug, Clone)]
pub struct RoutingDecision {
    pub account_id: Option<String>,
    pub model: String,
    pub score: f64,
    pub reason: String,
}

// ─── Core Components ──────────────────────────────────────────────────────

/// Routes requests to accounts based on balance, health, and weights.
pub struct AccountRouter {
    accounts: std::collections::HashMap<String, AccountConfig>,
    cost_trackers: std::collections::HashMap<String, f64>,
    request_counts: std::collections::HashMap<String, Vec<f64>>,
}

impl Default for AccountRouter {
    fn default() -> Self {
        Self::new()
    }
}

impl AccountRouter {
    pub fn new() -> Self {
        Self {
            accounts: std::collections::HashMap::new(),
            cost_trackers: std::collections::HashMap::new(),
            request_counts: std::collections::HashMap::new(),
        }
    }

    pub fn register_account(&mut self, config: AccountConfig) -> String {
        let id = config.id.clone();
        self.accounts.insert(id.clone(), config);
        self.cost_trackers.insert(id.clone(), 0.0);
        self.request_counts.insert(id.clone(), Vec::new());
        id
    }

    pub fn unregister_account(&mut self, account_id: &str) {
        self.accounts.remove(account_id);
        self.cost_trackers.remove(account_id);
        self.request_counts.remove(account_id);
    }

    fn compute_score(&self, account: &AccountConfig) -> (f64, String) {
        if !account.enabled || account.status != AccountStatus::Healthy {
            return (0.0, "disabled".to_string());
        }

        // Base score: proportional share of the pool
        let total_balance: f64 = self.accounts.values()
            .filter(|a| a.enabled && a.status == AccountStatus::Healthy)
            .map(|a| a.remaining_balance)
            .sum();

        if total_balance <= 0.0 {
            return (0.0, "no_balance".to_string());
        }

        let base_score = (account.remaining_balance / total_balance) * account.weight;

        // Health factor
        let health_factor = match account.status {
            AccountStatus::Healthy => 1.0,
            AccountStatus::RateLimited => 0.3,
            AccountStatus::Maintenance => 0.5,
            AccountStatus::Exhausted => 0.0,
        };

        // Rate limit factor (simplified - assume generous limits for demo)
        let rate_limit_factor = 1.0;

        // Latency factor (simplified - assume all accounts are fast)
        let latency_factor = 1.0;

        let score = base_score * health_factor * rate_limit_factor * latency_factor;
        (score, format!("balance={:.2}, weight={}", account.remaining_balance, account.weight))
    }

    pub fn route_request(
        &self,
        session_id: Option<&str>,
        prompt: &str,
        max_tokens: u32,
        force_account: Option<&str>,
    ) -> RoutingDecision {
        // Step 1: Check if we have any healthy accounts
        let healthy_accounts: Vec<_> = self.accounts.values()
            .filter(|acc| acc.enabled && acc.status == AccountStatus::Healthy)
            .collect();

        if healthy_accounts.is_empty() {
            return RoutingDecision {
                account_id: None,
                model: "none".to_string(),
                score: 0.0,
                reason: "No healthy accounts available".to_string(),
            };
        }

        // Step 2: Check sticky sessions (disabled by default)
        if let Some(sid) = session_id {
            if self.is_sticky_session_enabled() {
                if let Some(current_account_id) = self.get_current_session(sid) {
                    if let Some(account) = self.accounts.get(&current_account_id) {
                        let (score, reason) = self.compute_score(account);
                        return RoutingDecision {
                            account_id: Some(current_account_id.clone()),
                            model: account.model.clone(),
                            score,
                            reason: format!("sticky_session:{current_account_id}"),
                        };
                    }
                }
            }
        }

        // Step 3: Score all healthy accounts
        let mut scored: Vec<_> = self.accounts.iter()
            .filter(|(_, acc)| acc.enabled && acc.status == AccountStatus::Healthy)
            .map(|(aid, acc)| {
                let (score, reason) = self.compute_score(acc);
                (*aid, acc.clone(), score, reason)
            })
            .collect();

        if scored.is_empty() {
            return RoutingDecision {
                account_id: None,
                model: "none".to_string(),
                score: 0.0,
                reason: "no_healthy_accounts".to_string(),
            };
        }

        // Sort by score descending
        scored.sort_by(|a, b| b.2.partial_cmp(&a.2).unwrap_or(std::cmp::Ordering::Equal));

        let (best_account_id, best_account, best_score, _) = scored[0];

        // Step 4: Check budget constraints
        if best_account.budget_limit > 0.0 {
            let remaining = best_account.budget_limit - self.cost_trackers.get(&best_account_id).copied().unwrap_or(0.0);
            if remaining <= 0.0 {
                return RoutingDecision {
                    account_id: None,
                    model: "none".to_string(),
                    score: 0.0,
                    reason: format!("budget_exhausted:{best_account_id}"),
                };
            }
        }

        // Step 5: Select the best account
        RoutingDecision {
            account_id: Some(best_account_id.clone()),
            model: best_account.model.clone(),
            score: best_score,
            reason: format!("score={:.4}, {}", best_score, best_account.name),
        }
    }

    fn is_sticky_session_enabled(&self) -> bool {
        // In production, this would be configurable
        false
    }

    fn get_current_session(&self, session_id: &str) -> Option<String> {
        None // In production, load from DB/Redis
    }

    pub fn update_request_result(&mut self, account_id: &str, result: &serde_json::Value) {
        if let Some(account) = self.accounts.get(account_id) {
            let cost = result.get("cost").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let input_tokens = result.get("usage")
                .and_then(|u| u.get("input_tokens"))
                .and_then(|v| v.as_u64())
                .unwrap_or(0);
            let output_tokens = result.get("usage")
                .and_then(|u| u.get("output_tokens"))
                .and_then(|v| v.as_u64())
                .unwrap_or(0);

            // Update cost tracker
            if let Some(tracker) = self.cost_trackers.get_mut(account_id) {
                *tracker += cost;
            }

            // Update tokens used
            if let Some(acc) = self.accounts.get_mut(account_id) {
                acc.tokens_used += input_tokens + output_tokens;
                acc.last_used = Some(chrono::Utc::now());
            }

            // Track for rate limiting (simplified - just count requests per minute)
            if let Some(counts) = self.request_counts.get_mut(account_id) {
                counts.push(std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or(Duration::ZERO)
                    .as_secs_f64());
                // Keep only last 60 seconds
                let cutoff = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or(Duration::ZERO)
                    .as_secs_f64() - 60.0;
                counts.retain(|&t| t >= cutoff);
            }
        }
    }

    pub fn get_account_stats(&self, account_id: &str) -> Option<AccountConfig> {
        self.accounts.get(account_id).cloned()
    }
}

/// Tracks balance across multiple accounts and provides a virtual pool view.
pub struct BalanceTracker {
    router: Arc<Mutex<AccountRouter>>,
}

impl BalanceTracker {
    pub fn new(router: &AccountRouter) -> Self {
        Self {
            router: Arc::new(Mutex::new(router.clone())),
        }
    }

    pub fn get_virtual_pool_balance(&self) -> serde_json::Value {
        let router = self.router.lock().unwrap();
        let total_balance: f64 = router.accounts.values()
            .filter(|acc| acc.enabled && acc.status == AccountStatus::Healthy)
            .map(|acc| acc.remaining_balance)
            .sum();

        serde_json::json!({
            "pool_name": "LLM Gateway Pool",
            "balance_usd": (total_balance * 100.0).round() / 100.0,
            "tokens_available": if total_balance > 0.0 {
                (total_balance * 1_000_000.0 / 3e-6) as u64
            } else { 0 },
            "accounts": router.accounts.values()
                .filter(|acc| acc.enabled)
                .map(|acc| serde_json::json!({
                    "id": acc.id,
                    "name": acc.name,
                    "balance": (acc.remaining_balance * 100.0).round() / 100.0,
                    "status": acc.status,
                }))
                .collect::<Vec<_>>(),
        })
    }

    pub fn get_allocation(&self) -> serde_json::Value {
        let router = self.router.lock().unwrap();
        let total: f64 = router.accounts.values()
            .filter(|acc| acc.enabled && acc.status == AccountStatus::Healthy)
            .map(|acc| acc.remaining_balance)
            .sum();

        if total <= 0.0 {
            return serde_json::json!({});
        }

        serde_json::json!({
            "total": (total * 100.0).round() / 100.0,
            "accounts": router.accounts.values()
                .filter(|acc| acc.enabled && acc.status == AccountStatus::Healthy)
                .map(|acc| serde_json::json!({
                    "id": acc.id,
                    "percentage": ((acc.remaining_balance / total) * 100.0).round() / 100.0,
                }))
                .collect::<Vec<_>>(),
        })
    }
}

/// Estimates and tracks token usage across models.
pub struct TokenCounter {
    router: Arc<Mutex<AccountRouter>>,
}

impl TokenCounter {
    pub fn new(router: &AccountRouter) -> Self {
        Self {
            router: Arc::new(Mutex::new(router.clone())),
        }
    }

    pub fn estimate_cost(&self, model: &str, input_tokens: u64, output_tokens: u64) -> f64 {
        let rates = match model {
            "claude-3-haiku" => (0.25e-6, 1.25e-6),
            "claude-3-sonnet" => (3e-6, 15e-6),
            "claude-3-5-sonnet" => (3e-6, 15e-6),
            "claude-3-opus" => (15e-6, 75e-6),
            "codellama-7b" => (0.0, 0.0),
            _ => (3e-6, 15e-6), // Default to sonnet rates
        };

        input_tokens as f64 * rates.0 + output_tokens as f64 * rates.1
    }
}

// ─── Main Gateway ──────────────────────────────────────────────────────────

pub struct LLMGateway {
    router: AccountRouter,
    tracker: BalanceTracker,
    token_counter: TokenCounter,
    db_path: Option<String>,
}

impl LLMGateway {
    pub fn new(db_path: Option<&str>) -> Self {
        let router = AccountRouter::new();
        let tracker = BalanceTracker::new(&router);
        let token_counter = TokenCounter::new(&router);
        Self {
            router,
            tracker,
            token_counter,
            db_path: db_path.map(|s| s.to_string()),
        }
    }

    pub fn register_account(&mut self, config: AccountConfig) -> String {
        let id = self.router.register_account(config.clone());
        // Persist to database if configured
        if let Some(ref path) = self.db_path {
            Self::persist_account(path, &config);
        }
        id
    }

    pub fn unregister_account(&mut self, account_id: &str) {
        self.router.unregister_account(account_id);
        if let Some(ref path) = self.db_path {
            Self::remove_from_db(path, account_id);
        }
    }

    fn persist_account(path: &str, config: &AccountConfig) {
        // For now, we use in-memory only. In production, this would write to SQLite.
    }

    fn remove_from_db(path: &str, account_id: &str) {
        // Would delete from database
    }

    pub fn complete(
        &mut self,
        session_id: &str,
        prompt: &str,
        max_tokens: u32,
        force_account: Option<&str>,
    ) -> serde_json::Value {
        // Route the request
        let decision = self.router.route_request(Some(session_id), prompt, max_tokens, force_account);

        if decision.account_id.is_none() {
            return serde_json::json!({
                "error": {
                    "type": "routing_error",
                    "message": decision.reason,
                }
            });
        }

        let account = self.router.accounts.get(&decision.account_id).unwrap();

        // In a real implementation, this would forward to the actual Claude API.
        // For the plugin, we return a mock response.
        let result = serde_json::json!({
            "id": format!("{}-cm-{}", account.id, std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()),
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": format!("[ROUTED TO {}] Model: {} | Cost estimate: ${:.6}",
                        account.name, account.model,
                        self.token_counter.estimate_cost(&account.model, 128, 64)),
                }
            ],
            "model": account.model.clone(),
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 128,
                "output_tokens": 64,
            },
            "cost": self.token_counter.estimate_cost(&account.model, 128, 64),
        });

        // Record the result
        self.router.update_request_result(&decision.account_id.unwrap(), &result);

        result
    }

    pub fn get_virtual_pool(&self) -> serde_json::Value {
        self.tracker.get_virtual_pool_balance()
    }

    pub fn get_account_stats(&self, account_id: &str) -> Option<serde_json::Value> {
        self.router.get_account_stats(account_id).map(|acc| serde_json::json!({
            "id": acc.id,
            "name": acc.name,
            "status": acc.status,
            "remaining_balance": (acc.remaining_balance * 100.0).round() / 100.0,
            "tokens_used": acc.tokens_used,
            "total_cost_usd": (acc.total_cost_usd * 100000.0).round() / 100000.0,
        }))
    }

    pub fn get_all_accounts(&self) -> Vec<serde_json::Value> {
        self.router.accounts.values()
            .filter(|acc| acc.enabled)
            .map(|acc| serde_json::json!({
                "id": acc.id,
                "name": acc.name,
                "status": acc.status,
                "remaining_balance": (acc.remaining_balance * 100.0).round() / 100.0,
                "model": acc.model,
                "weight": acc.weight,
            }))
            .collect()
    }
}
