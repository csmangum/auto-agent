# Mock Crew Requirements Traceability

## Requirements Checklist

Use this document to track implementation progress and acceptance criteria.

---

## Functional Requirements

### FR-1: Mock Claimant
- [ ] **Implement** Mock Claimant agent/module
- [ ] **Acceptance**: Can submit claim input JSON via programmatic API
- [ ] **Acceptance**: When `send_user_message` targets claimant, produces response text
- [ ] **Acceptance**: Response is derivable from claim context + message content
- [ ] **Acceptance**: `record_user_response` can be called with mock response
- [ ] **Config**: `MOCK_CLAIMANT_ENABLED`, `MOCK_CLAIMANT_RESPONSE_STRATEGY`

### FR-2: Mock Image Generator
- [ ] **Implement** Mock Image Generator agent/module
- [ ] **Acceptance**: Generates placeholder image for claim (vehicle + damage context)
- [ ] **Acceptance**: `analyze_damage_photo` returns structured result without calling vision API
- [ ] **Acceptance**: Result includes `severity`, `parts_affected`, `consistency_with_description`
- [ ] **Acceptance**: Result is consistent with claim's `damage_description`
- [ ] **Config**: `MOCK_IMAGE_GENERATOR_ENABLED`, `MOCK_IMAGE_MODE`, `MOCK_VISION_ANALYSIS_SOURCE`

### FR-3: Mock Document Generator
- [ ] **Implement** Mock Document Generator agent/module
- [ ] **Acceptance**: Generates repair estimate JSON/PDF for claim context
- [ ] **Acceptance**: Estimate line items align with damage description
- [ ] **Acceptance**: Can generate damage photo references (delegates to Image Generator)
- [ ] **Config**: `MOCK_DOCUMENT_GENERATOR_ENABLED`, `MOCK_DOCUMENT_OUTPUT_FORMAT`

### FR-4: Mock Repair Shop
- [ ] **Implement** Mock Repair Shop agent/module
- [ ] **Acceptance**: When `send_user_message` targets repair_shop, produces response
- [ ] **Acceptance**: Can return supplemental estimate when configured
- [ ] **Acceptance**: Response aligns with shop assignment and original estimate
- [ ] **Config**: `MOCK_REPAIR_SHOP_ENABLED`, `MOCK_REPAIR_SHOP_BEHAVIOR`

### FR-5: Mock Third Party
- [ ] **Implement** Mock Third Party agent/module
- [ ] **Acceptance**: When `send_demand_letter` invoked, produces configurable response
- [ ] **Acceptance**: Supports accept, reject, negotiate, no_response
- [ ] **Acceptance**: Settlement amount follows `MOCK_THIRD_PARTY_SETTLEMENT_RATIO`
- [ ] **Config**: `MOCK_THIRD_PARTY_ENABLED`, `MOCK_THIRD_PARTY_RESPONSE`, `MOCK_THIRD_PARTY_SETTLEMENT_RATIO`

### FR-6: Mock Notifier
- [ ] **Implement** Mock Notifier
- [ ] **Acceptance**: `notify_user` / `notify_claimant` do not send real email/SMS
- [ ] **Acceptance**: Delivery intent is logged
- [ ] **Acceptance**: Optional: triggers Mock Claimant/Repair Shop response
- [ ] **Config**: `MOCK_NOTIFIER_ENABLED`, `MOCK_NOTIFIER_AUTO_RESPOND`

### FR-7: Mock Webhook Receiver
- [ ] **Implement** Mock Webhook Receiver
- [ ] **Acceptance**: Outbound webhooks are intercepted (no real HTTP)
- [ ] **Acceptance**: Payloads are stored for test assertions
- [ ] **Acceptance**: Configurable HTTP response status
- [ ] **Config**: `MOCK_WEBHOOK_ENABLED`, `MOCK_WEBHOOK_CAPTURE_PATH`, `MOCK_WEBHOOK_RESPONSE_STATUS`

### FR-8: Independent Configuration
- [ ] **Acceptance**: Each mock role can be enabled/disabled via env
- [ ] **Acceptance**: Disabled mocks fall back to real/stub behavior (or no-op)

### FR-9: Claim-Context Derivation
- [ ] **Acceptance**: All mock outputs use claim fields: `damage_description`, `incident_description`, `vehicle_*`, `policy_number`
- [ ] **Acceptance**: Mock Image Generator severity matches damage_description keywords
- [ ] **Acceptance**: Mock Claimant response references claim details when relevant

### FR-10: Seeded Randomness
- [ ] **Acceptance**: `MOCK_CREW_SEED` produces deterministic outputs across runs
- [ ] **Acceptance**: Same seed + same claim = same mock outputs

---

## Non-Functional Requirements

### NFR-1: Minimal Latency
- [ ] **Acceptance**: Placeholder image generation < 50ms
- [ ] **Acceptance**: Vision analysis mock < 10ms

### NFR-2: Pytest Integration
- [ ] **Acceptance**: `mock_crew` fixture available in tests
- [ ] **Acceptance**: Works with `temp_db`, `seeded_temp_db`, `claim_context`
- [ ] **Acceptance**: Fixture resets mock state between tests

### NFR-3: No External API Keys
- [ ] **Acceptance**: With all mocks enabled, no OPENAI_API_KEY or similar required for E2E
- [ ] **Acceptance**: Vision analysis uses mock, not real vision model

### NFR-4: Environment-Driven Config
- [ ] **Acceptance**: All config via env vars (no hardcoded paths in CI)
- [ ] **Acceptance**: Works in GitHub Actions / typical CI

---

## Test Scenario Coverage

| Scenario | FRs | Status |
|----------|-----|--------|
| TS-1: E2E partial loss with damage photos | FR-1, FR-2, FR-4 | |
| TS-2: E2E total loss with valuation | FR-1, FR-2 | |
| TS-3: Follow-up: request photos → claimant responds | FR-1, FR-6 | |
| TS-4: Subrogation: demand → third party accepts | FR-5 | |
| TS-5: Webhook assertions: repair.authorized | FR-7 | |
| TS-6: Fraud: inconsistent damage description | FR-2 | |
| TS-7: Supplemental estimate flow | FR-4, FR-3 | |

---

## Implementation Order

1. **Phase 1**: FR-2 (Mock Vision), FR-6 (Mock Notifier), FR-1 (Mock Claimant), FR-8, FR-9, FR-10, NFR-*
2. **Phase 2**: FR-3 (Mock Document), FR-4 (Mock Repair Shop)
3. **Phase 3**: FR-5 (Mock Third Party), FR-7 (Mock Webhook)
