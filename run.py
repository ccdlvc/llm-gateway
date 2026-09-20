#!/usr/bin/env python3
"""Run the LLM Gateway demo."""

import sys
sys.path.insert(0, '.')

from gateway import LLMGateway, AccountConfig
import json

gateway = LLMGateway()

# Register accounts
accounts = [
    AccountConfig(id='acc-1', name='Team Alpha', api_key='sk-a', weight=1.0, remaining_balance=100.0),
    AccountConfig(id='acc-2', name='Team Beta', api_key='sk-b', weight=1.0, remaining_balance=40.0),
    AccountConfig(id='acc-3', name='Team Gamma', api_key='sk-c', weight=1.0, remaining_balance=160.0),
]

for acc in accounts:
    gateway.register_account(acc)

session_id = 'sess-demo'
gateway.start_session(session_id)

print('=== Virtual Pool ===')
pool = gateway.get_virtual_pool()
print(json.dumps(pool, indent=2))

print('\n=== Routing 5 requests ===')
for i in range(5):
    result = gateway.complete(session_id, f'Prompt {i+1}: Explain concept {i+1}')
    model = result.get('model', '')
    print(f'  Request {i+1} -> {model}')

print('\n=== Updated Pool ===')
pool = gateway.get_virtual_pool()
print(json.dumps(pool, indent=2))
