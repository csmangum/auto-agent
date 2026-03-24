# Mock Crew Design: Comprehensive External Interaction Simulation

## 1. Executive Summary

The **Mock Crew** is a test-oriented multi-agent system that simulates all external (third-party) interactions with the claim system. It enables end-to-end testing without real people, services, or integrations—reducing cost, improving reproducibility, and accelerating development.

---

## 2. Goals and Non-Goals

### Goals

- **Full isolation**: Run claim workflows without external API calls, email/SMS, or human actors.
- **Claim-specific realism**: Mock outputs (images, documents, responses) are tailored to each claim's context (VIN, damage description, incident type).
- **Reproducibility**: Seeded randomness for deterministic test runs.
- **Comprehensive coverage**: Mock every external touchpoint identified in the claim system.
- **Pluggable**: Enable/disable individual mock roles via configuration.

### Non-Goals

- **Production use**: Mock Crew is for testing only; never used in production.
- **Replacing unit tests**: Unit tests with mocks/stubs remain; Mock Crew supports integration and E2E.
- **Realistic human behavior**: Simulated responses are plausible but not psychologically accurate.

---

## 3. External Touchpoints Inventory

Based on codebase analysis, the following external interactions must be mocked:

| Touchpoint | Real Implementation | Mock Responsibility |
|------------|---------------------|---------------------|
| **Vision / damage photos** | `analyze_damage_photo` → litellm/vision model | Generate claim-specific damage images; return structured analysis without calling real vision API |
| **Claimant** | Human files claim, receives `send_user_message`, responds via `record_user_response` | Submit claims; auto-respond to follow-up messages with plausible content |
| **Policy lookup** | PolicyAdapter (mock/stub) | Already mocked via `mock_db.json`; ensure coverage |
| **Valuation** | ValuationAdapter (mock/stub) | Already mocked; ensure coverage |
| **Repair shop** | RepairShopAdapter, receives follow-ups | Intercept repair-shop `notify_user` calls; queue configurable acknowledgment (`MOCK_REPAIR_SHOP_ENABLED`) |
| **Parts catalog** | PartsAdapter (mock/stub) | Already mocked |
| **SIU** | SIUAdapter (mock/stub) | Already mocked |
| **Document generation (input)** | Claimant uploads estimates, photos, PDFs | Generate mock claimant documents (estimates, damage photos) for claim context |
| **Notifications** | `notify_user` → email/SMS/portal | Mock delivery; optionally auto-trigger mock claimant response (`MOCK_NOTIFIER_ENABLED`) |
| **Webhooks** | Outbound HTTP to external URLs | Capture payloads in-memory for assertions; suppress real HTTP (`MOCK_WEBHOOK_CAPTURE_ENABLED`) |
| **Subrogation** | `send_demand_letter` → third party | Return configurable outcome—accept, reject, or negotiate (`MOCK_THIRD_PARTY_ENABLED`) |
| **Storage** | Local/S3 for attachments | Mock storage adapter for tests |

---

## 4. Mock Crew Roles

### 4.1 Mock Claimant Agent

**Purpose**: Plays the role of the customer/policyholder who files claims and responds to follow-up requests.

**Responsibilities**:
- Submit claim inputs (via API or programmatic interface) with realistic, claim-type-specific data.
- When `send_user_message` targets `claimant` or `policyholder`, produce a simulated response.
- Response content is derived from claim context (incident description, damage, policy) and the message content (e.g., "Please provide photos" → respond with mock photo URLs).

**Inputs**:
- Claim scenario (type, incident, damage, policy).
- Follow-up message content and `message_id`.
- Optional: response delay (for async simulation).

**Outputs**:
- Claim input JSON (for submission).
- Response text and optional attachment URLs (for `record_user_response`).

**Configuration**:
- `MOCK_CLAIMANT_ENABLED`: bool
- `MOCK_CLAIMANT_RESPONSE_DELAY_MS`: int (0 for sync)
- `MOCK_CLAIMANT_RESPONSE_STRATEGY`: `immediate` | `delayed` | `refuse` | `partial`

---

### 4.2 Mock Image Generator Agent

**Purpose**: Generate vehicle damage images specific to a claim, and provide vision analysis results without calling a real vision model.

**Responsibilities**:
- **Image generation**: Given claim context (vehicle make/model/year, damage description, severity), produce a synthetic or placeholder image. Options:
  - **Placeholder**: Deterministic placeholder (e.g., colored rectangle with metadata overlay) for fast tests.
  - **Model-based**: Use a diffusion/vision model to generate realistic damage images (optional, heavier).
- **Vision analysis**: When `analyze_damage_photo` is invoked, return a structured result (severity, parts_affected, consistency_with_description) derived from claim context instead of calling the real vision API.

**Inputs**:
- Claim: `damage_description`, `vehicle_make`, `vehicle_model`, `vehicle_year`, `incident_description`.
- Optional: `image_url` (for analysis path) or generation request.

**Outputs**:
- Image URL (file path or data URL) for generated image.
- Vision analysis JSON: `{ severity, parts_affected, consistency_with_description, notes }`.

**Configuration**:
- `MOCK_IMAGE_GENERATOR_ENABLED`: bool
- `MOCK_IMAGE_MODE`: `placeholder` | `generated` (model-based)
- `MOCK_VISION_ANALYSIS_SOURCE`: `claim_context` | `deterministic` | `passthrough` (passthrough = real API, for comparison)

---

### 4.3 Mock Document Generator Agent

**Purpose**: Create claimant-side documents (repair estimates, PDFs, photos) that the claim system consumes.

**Responsibilities**:
- Generate mock repair estimates (JSON/PDF) with line items, labor, parts, totals—aligned with claim damage.
- Generate mock damage photo references (delegate to Mock Image Generator).
- Produce PDFs (e.g., police report, medical records for BI) when needed for claim type.

**Inputs**:
- Claim context: type, damage, vehicle, policy.
- Document type: `estimate`, `damage_photo`, `police_report`, `medical_record`, etc.

**Outputs**:
- Document URL (file path or storage key).
- Metadata (e.g., estimate total, shop name).

**Configuration**:
- `MOCK_DOCUMENT_GENERATOR_ENABLED`: bool
- `MOCK_DOCUMENT_OUTPUT_FORMAT`: `json` | `pdf` | `both`

---

### 4.4 Mock Repair Shop Agent

**Purpose**: Simulate repair shop behavior beyond the existing RepairShopAdapter (which provides shop data). Handles follow-up messages and estimate supplements.

**Responsibilities**:
- When `send_user_message` targets `repair_shop`, produce a simulated response (e.g., "Estimate ready", "Supplement needed").
- When supplemental estimate is requested, return mock supplemental line items.
- Optionally simulate delays or refusals for negative testing.

**Inputs**:
- Claim context, shop assignment, original estimate.
- Follow-up message content.

**Outputs**:
- Response text.
- Optional: supplemental estimate JSON.

**Configuration**:
- `MOCK_REPAIR_SHOP_ENABLED`: bool
- `MOCK_REPAIR_SHOP_BEHAVIOR`: `cooperative` | `delayed` | `supplement_required` | `refuse`

---

### 4.5 Mock Third Party / Subrogation Agent

**Purpose**: Simulate the at-fault party (or their insurer) in subrogation flows.

**Responsibilities**:
- When `send_demand_letter` is invoked, produce a simulated response: accept, reject, negotiate, or no response.
- Response amount and timing configurable for test scenarios.

**Inputs**:
- Demand letter payload (case_id, claim_id, amount_sought).
- Claim context (liability, coverage).

**Outputs**:
- Response type: `accepted` | `rejected` | `negotiated` | `no_response`.
- Settlement amount (if accepted/negotiated).
- Response delay (optional).

**Configuration**:
- `MOCK_THIRD_PARTY_ENABLED`: bool
- `MOCK_THIRD_PARTY_RESPONSE`: `accept` | `reject` | `negotiate` | `no_response`
- `MOCK_THIRD_PARTY_SETTLEMENT_RATIO`: float (e.g., 0.9 = 90% of demand)

---

### 4.6 Mock Notifier Agent

**Purpose**: Intercept notification delivery (email, SMS, portal) and optionally trigger mock user responses.

**Responsibilities**:
- When `notify_user` or `notify_claimant` is called, log the intent and optionally invoke Mock Claimant / Mock Repair Shop to produce a response.
- No real email/SMS sent.

**Inputs**:
- Notification type, user type, claim_id, message/template.

**Outputs**:
- Delivery logged; optionally enqueue mock response for `record_user_response`.

**Configuration**:
- `MOCK_NOTIFIER_ENABLED`: bool
- `MOCK_NOTIFIER_AUTO_RESPOND`: bool (trigger mock claimant/shop response)

---

### 4.7 Mock Webhook Receiver

**Purpose**: Capture outbound webhook payloads for assertions; optionally simulate webhook consumer behavior.

**Responsibilities**:
- Intercept `dispatch_webhook` / `dispatch_repair_authorized` calls.
- Store payloads in memory or file for test assertions.
- Optionally return simulated HTTP responses (e.g., 500 for retry testing).

**Inputs**:
- Webhook event type, payload, URL.

**Outputs**:
- Stored payloads; configurable HTTP status for simulation.

**Configuration**:
- `MOCK_WEBHOOK_ENABLED`: bool
- `MOCK_WEBHOOK_CAPTURE_PATH`: optional file path for payload dump
- `MOCK_WEBHOOK_RESPONSE_STATUS`: int (default 200)

---

## 5. Architecture

### 5.1 Integration Points

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CLAIM SYSTEM (SUT)                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │
│  │ Router Crew │  │ Workflow    │  │ Follow-up   │  │ Subrogation │   │
│  │             │  │ Crews       │  │ Crew        │  │ Crew        │   │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘   │
│         │                │                │                │          │
│         ▼                ▼                ▼                ▼          │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                    ADAPTER / TOOL LAYER                          │  │
│  │  analyze_damage_photo | notify_user | send_demand_letter | ...   │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────┬───────────────────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ MOCK VISION         │  │ MOCK NOTIFIER       │  │ MOCK WEBHOOK         │
│ (image + analysis)  │  │ (delivery + trigger)│  │ (capture payloads)   │
└─────────────────────┘  └──────────┬──────────┘  └─────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ MOCK CLAIMANT       │  │ MOCK REPAIR SHOP    │  │ MOCK THIRD PARTY     │
│ (submit + respond)  │  │ (respond + supp)    │  │ (subrogation resp)   │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
```

### 5.2 Wiring Strategy

- **Adapter swap**: Use env vars (e.g., `VISION_ADAPTER=mock`, `NOTIFICATION_ADAPTER=mock`) to swap real implementations for mock implementations at runtime.
- **Test fixtures**: `mock_crew` fixture that starts all enabled mock agents and resets state between tests.
- **CrewAI integration**: Mock agents can be CrewAI agents with tools that the claim system "calls" indirectly—or simpler: Python functions that are injected into the adapter/tool layer.

### 5.3 Mock Response Data Flow

**Follow-up flow (Mock Claimant)**:
```
send_user_message(claimant, "Please provide damage photos")
    → Mock Notifier intercepts (no real email)
    → If MOCK_NOTIFIER_AUTO_RESPOND: Mock Claimant generates response
    → Response stored in mock queue; test or async worker calls record_user_response
```

**Synchronous test flow**: Test calls `mock_claimant.respond_to_message(claim_id, message_id)` → gets response text → calls `record_user_response(message_id, response_text)`.

**Async flow** (optional): Mock Notifier enqueues; background task or fixture drains queue and calls `record_user_response` after configurable delay.

### 5.4 Mock Intercept Precedence

`notify_user()` checks mock intercepts in order:

1. **General notifier** (`MOCK_NOTIFIER_ENABLED`) — checked first for *all* user types. When enabled, `mock_notify_user` handles the call and returns immediately, regardless of user type.
2. **Repair-shop-specific** (`MOCK_REPAIR_SHOP_ENABLED`) — checked only for `user_type=repair_shop`, and only if the general notifier intercept did not fire.

If both `MOCK_NOTIFIER_ENABLED=true` and `MOCK_REPAIR_SHOP_ENABLED=true`, the general notifier takes precedence and the repair-shop intercept is never reached. This is by design: the general notifier provides a single capture point for all notification types, while the repair-shop mock exists for scenarios where only shop-specific acknowledgments need testing (with the general notifier disabled).

---

## 6. Requirements Summary

### 6.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Mock Crew SHALL provide a Mock Claimant that can submit claims and respond to follow-up messages. | P0 |
| FR-2 | Mock Crew SHALL provide a Mock Image Generator that produces claim-specific damage images and vision analysis without calling real vision API. | P0 |
| FR-3 | Mock Crew SHALL provide a Mock Document Generator for estimates, photos, and other claimant documents. | P1 |
| FR-4 | Mock Crew SHALL provide a Mock Repair Shop that responds to follow-up messages. | P1 |
| FR-5 | Mock Crew SHALL provide a Mock Third Party that responds to demand letters. | P1 |
| FR-6 | Mock Crew SHALL provide a Mock Notifier that intercepts and logs notifications. | P0 |
| FR-7 | Mock Crew SHALL provide a Mock Webhook Receiver that captures outbound webhook payloads. | P1 |
| FR-8 | Each mock role SHALL be independently configurable (enable/disable). | P0 |
| FR-9 | Mock outputs SHALL be derivable from claim context (VIN, damage, incident, policy). | P0 |
| FR-10 | Mock Crew SHALL support seeded randomness for reproducible tests. | P0 |

### 6.2 Non-Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-1 | Mock Crew SHALL add minimal latency; placeholder mode SHALL be near-instant. | P0 |
| NFR-2 | Mock Crew SHALL integrate with existing pytest fixtures (`temp_db`, `seeded_temp_db`, `claim_context`). | P0 |
| NFR-3 | Mock Crew SHALL NOT require external API keys when fully mocked. | P0 |
| NFR-4 | Mock Crew configuration SHALL be environment-driven for CI compatibility. | P1 |

### 6.3 Test Scenario Requirements

| ID | Scenario | Mock Roles Involved |
|----|----------|----------------------|
| TS-1 | E2E partial loss with damage photos | Mock Image Generator, Mock Claimant, Mock Repair Shop |
| TS-2 | E2E total loss with valuation | Mock Claimant, Mock Image Generator |
| TS-3 | Follow-up flow: request photos → claimant responds | Mock Claimant, Mock Notifier |
| TS-4 | Subrogation: demand letter → third party accepts | Mock Third Party |
| TS-5 | Webhook assertions: repair.authorized payload | Mock Webhook Receiver |
| TS-6 | Fraud scenario with inconsistent damage description | Mock Image Generator (inconsistent analysis) |
| TS-7 | Supplemental estimate flow | Mock Repair Shop |

---

## 7. Implementation Phases

### Phase 1: Core Mocks (P0)
- Mock Vision (analyze_damage_photo override + placeholder image generation)
- Mock Notifier (intercept notify_user)
- Mock Claimant (submit + respond)
- Configuration and fixture wiring

### Phase 2: Document and Shop (P1)
- Mock Document Generator
- Mock Repair Shop responses

### Phase 3: Subrogation and Webhooks (P1)
- Mock Third Party
- Mock Webhook Receiver

### Phase 4: Optional Enhancements
- Model-based image generation (optional)
- Async response simulation (delayed mock claimant)
- Negative scenarios (refuse, supplement_required)

---

## 8. Configuration Reference

```bash
# Global
MOCK_CREW_ENABLED=true
MOCK_CREW_SEED=42

# Mock Claimant
MOCK_CLAIMANT_ENABLED=true
MOCK_CLAIMANT_RESPONSE_STRATEGY=immediate

# Mock Image Generator
MOCK_IMAGE_GENERATOR_ENABLED=true
MOCK_IMAGE_MODE=placeholder
MOCK_VISION_ANALYSIS_SOURCE=claim_context

# Mock Document Generator
MOCK_DOCUMENT_GENERATOR_ENABLED=true

# Mock Repair Shop
MOCK_REPAIR_SHOP_ENABLED=true
MOCK_REPAIR_SHOP_BEHAVIOR=cooperative

# Mock Third Party
MOCK_THIRD_PARTY_ENABLED=true
MOCK_THIRD_PARTY_RESPONSE=accept
MOCK_THIRD_PARTY_SETTLEMENT_RATIO=0.95

# Mock Notifier
MOCK_NOTIFIER_ENABLED=true
MOCK_NOTIFIER_AUTO_RESPOND=true

# Mock Webhook
MOCK_WEBHOOK_ENABLED=true
MOCK_WEBHOOK_CAPTURE_PATH=/tmp/mock_webhooks.jsonl
```

---

## 9. Open Questions

1. **Image generation**: Use a lightweight placeholder (e.g., PIL-generated image with text overlay) vs. optional diffusion model for higher fidelity?
2. **Mock Claimant personality**: Should we support multiple "personas" (cooperative, evasive, angry) for negative testing?
3. **CrewAI vs. plain functions**: Implement mock agents as CrewAI agents (for consistency) or as plain Python modules (simpler, faster)?

---

## 10. References

- [Adapters](adapters.md) – Policy, Valuation, RepairShop, Parts, SIU
- [Tools](tools.md) – Full tool reference
- [Webhooks](webhooks.md) – Webhook events and configuration
- [Crews](crews.md) – Workflow crews and agents
