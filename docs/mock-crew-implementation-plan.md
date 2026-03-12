# Mock Crew Implementation Plan

This plan details how to implement the Mock Crew with **OpenRouter for image generation**. Follow the phases in order; each phase builds on the previous.

---

## Prerequisites

- OpenRouter API key (same as existing `OPENAI_API_KEY` / `OPENROUTER_API_KEY` when using OpenRouter base)
- Python 3.11+, existing venv
- Familiarity with: adapters (`src/claim_agent/adapters/`), tools (`src/claim_agent/tools/`), config (`src/claim_agent/config/`)

---

## OpenRouter Image Generation

OpenRouter supports image generation via `/api/v1/chat/completions` with the `modalities` parameter:

- **Image-only models** (e.g., Flux, Sourceful): `modalities: ["image"]`
- **Text + image models** (e.g., Gemini): `modalities: ["image", "text"]`

Generated images are returned as base64-encoded data URLs in the assistant message.

**Discover models:**
```bash
curl "https://openrouter.ai/api/v1/models?output_modality=image"
```

**Example models** (check OpenRouter docs for current list):
- `google/gemini-2.0-flash-exp:free` (image + text)
- `black-forest-labs/flux-1.1-pro` (image)
- `openai/gpt-4o` (vision; for analysis, not generation)

**Config to add:**
- `MOCK_IMAGE_MODEL` – OpenRouter model ID for image generation (e.g., `google/gemini-2.0-flash-exp`)
- Reuse `OPENAI_API_BASE`, `OPENAI_API_KEY` (or `OPENROUTER_API_KEY`) for OpenRouter

---

## Phase 1: Configuration and Mock Crew Foundation

### 1.1 Add Mock Crew Settings

**File:** `src/claim_agent/config/settings_model.py`

Add a new settings block (or extend an existing one):

```python
class MockCrewConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_prefix="MOCK_CREW_")
    enabled: bool = Field(default=False, validation_alias="ENABLED")
    seed: int | None = Field(default=None, validation_alias="SEED")

class MockImageConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_prefix="MOCK_IMAGE_")
    enabled: bool = Field(default=False, validation_alias="GENERATOR_ENABLED")
    model: str = Field(default="google/gemini-2.0-flash-exp", validation_alias="MODEL")
    # For vision analysis: "openrouter" = real API, "claim_context" = derive from claim
    vision_analysis_source: str = Field(default="claim_context", validation_alias="VISION_ANALYSIS_SOURCE")
```

Wire these into the root `Settings` model (e.g., `mock_crew: MockCrewConfig`, `mock_image: MockImageConfig`).

**Tasks:**
- [ ] Add `MockCrewConfig` and `MockImageConfig` classes
- [ ] Add `mock_crew` and `mock_image` fields to root Settings
- [ ] Add `get_mock_crew_config()` and `get_mock_image_config()` in `settings.py` if needed

### 1.2 Add Adapter Backend for Vision

**File:** `src/claim_agent/config/settings_model.py` (or wherever adapter backends are defined)

Add `VISION_ADAPTER` with values `real` | `mock`:
- `real` – current behavior (litellm vision model)
- `mock` – derive analysis from claim context, no API call

**File:** `src/claim_agent/config/settings.py`

- [ ] Add `get_adapter_backend("vision")` support (or equivalent)
- [ ] Ensure `VALID_ADAPTER_BACKENDS` includes `vision` if using the adapter registry pattern

---

## Phase 2: Image Generation via OpenRouter

### 2.1 Create Image Generator Module

**New file:** `src/claim_agent/mock_crew/image_generator.py`

**Responsibilities:**
- Call OpenRouter with `modalities: ["image"]` (or `["image","text"]`)
- Build prompt from claim context: vehicle make/model/year, damage description, incident type
- Return image as file path (save to attachment storage) or data URL

**Prompt template (example):**
```
Generate a single realistic photo of vehicle damage for an insurance claim.
Vehicle: {year} {make} {model}
Damage description: {damage_description}
Incident: {incident_description}
Style: Single clear photo, daylight, showing the damaged area. No text or watermarks.
```

**API call pattern (OpenRouter):**
```python
import requests

url = "https://openrouter.ai/api/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}
payload = {
    "model": model,  # from MOCK_IMAGE_MODEL, e.g. google/gemini-2.0-flash-exp
    "messages": [{"role": "user", "content": prompt}],
    "modalities": ["image", "text"],  # or ["image"] for image-only models
}
resp = requests.post(url, headers=headers, json=payload)
# Response: assistant message content may include base64 data URLs
# Format: content[].image_url.url = "data:image/png;base64,..."
```

**Tasks:**
- [ ] Implement `generate_damage_image(claim_context: dict) -> str` returning file path or data URL
- [ ] Save generated image to `attachment_storage_path` with deterministic name when seed is set
- [ ] Handle OpenRouter-specific response format (base64 in message content)
- [ ] Add logging and error handling (return placeholder path on failure if desired)

### 2.2 OpenRouter Image Response Parsing

Image generation models return images in the assistant message. Structure varies:
- Some return `content: [{ type: "image_url", image_url: { url: "data:image/..." } }]`
- Some return base64 in a different structure

**Tasks:**
- [ ] Inspect OpenRouter docs for the exact response format of your chosen model
- [ ] Implement robust extraction of base64 image from response
- [ ] Decode and save to disk; return `file:///path/to/image.png`

---

## Phase 3: Mock Vision Analysis

### 3.1 Create Mock Vision Adapter

**New file:** `src/claim_agent/adapters/vision.py` (or `mock_crew/vision_mock.py`)

**Interface:**
```python
def analyze_damage_photo_mock(image_url: str, damage_description: str | None, claim_context: dict | None) -> str:
    """Return JSON analysis derived from claim context, no API call."""
```

**Logic:**
- Parse `damage_description` for keywords: "total", "totaled", "destroyed" → severity `total_loss`
- "bumper", "fender", "door", etc. → `parts_affected`
- If `damage_description` present and matches inferred parts → `consistency_with_description: "consistent"`
- Optional: use simple rules or a tiny local model for more nuance

**Tasks:**
- [ ] Implement `analyze_damage_photo_mock`
- [ ] Add keyword → severity mapping
- [ ] Add keyword → parts_affected extraction

### 3.2 Wire Vision Adapter into vision_logic

**File:** `src/claim_agent/tools/vision_logic.py`

Refactor to support adapter:

```python
def analyze_damage_photo_impl(image_url: str, damage_description: str | None = None, claim_context: dict | None = None) -> str:
    from claim_agent.config.settings import get_adapter_backend  # or equivalent
    backend = get_adapter_backend("vision")  # or get_mock_image_config().vision_analysis_source
    if backend == "mock" or (get_mock_crew_config().enabled and get_mock_image_config().vision_analysis_source == "claim_context"):
        return analyze_damage_photo_mock(image_url, damage_description, claim_context)
    # existing litellm path
```

**Note:** `claim_context` may not be passed today. You have two options:
- **A)** Add optional `claim_context` to the tool signature and pass it from the crew/agent when available
- **B)** Use only `damage_description` in the mock (simpler; mock infers from that)

**Tasks:**
- [ ] Add `claim_context` parameter to `analyze_damage_photo_impl` (optional)
- [ ] Add branch for mock vision when `VISION_ADAPTER=mock` or mock crew enabled
- [ ] Ensure `analyze_damage_photo` tool passes through (CrewAI tool wraps `_impl`)

---

## Phase 4: Mock Claimant

### 4.1 Create Mock Claimant Module

**New file:** `src/claim_agent/mock_crew/claimant.py`

**Responsibilities:**
- `generate_claim_input(scenario: dict) -> dict` – produce `ClaimInput`-shaped dict for submission
- `respond_to_message(claim_id: str, message_content: str, claim_context: dict) -> str` – produce response text

**Response logic:**
- If message asks for photos → "I've uploaded the photos to the portal" or return mock image URLs
- If message asks for estimate → "I'll get the estimate from the shop and send it"
- Generic: "I'll provide that information shortly" or similar
- Use `claim_context` (incident, damage) to make responses coherent

**Tasks:**
- [ ] Implement `generate_claim_input` with scenario keys: claim_type, incident, damage, vehicle, policy
- [ ] Implement `respond_to_message` with simple template/rule-based responses
- [ ] Add `MOCK_CLAIMANT_ENABLED`, `MOCK_CLAIMANT_RESPONSE_STRATEGY` to config

---

## Phase 5: Mock Notifier

### 5.1 Intercept notify_user / notify_claimant

**File:** `src/claim_agent/notifications/user.py` (and `claimant.py` if separate)

Add a check at the top:

```python
def notify_user(...):
    if get_mock_crew_config().enabled and get_mock_notifier_config().enabled:
        _mock_notify_user(...)  # log + optionally enqueue mock response
        return True  # pretend delivered
    # existing path
```

**New file:** `src/claim_agent/mock_crew/notifier.py`

- [ ] Implement `_mock_notify_user` – log (user_type, claim_id, message)
- [ ] If `MOCK_NOTIFIER_AUTO_RESPOND`: call Mock Claimant's `respond_to_message`, store in queue
- [ ] Provide `get_pending_mock_responses(claim_id) -> list` for tests to drain and call `record_user_response`

---

## Phase 6: Test Fixtures and Integration

### 6.1 Create mock_crew Fixture

**File:** `tests/conftest.py` (or `tests/fixtures/mock_crew.py`)

```python
@pytest.fixture
def mock_crew(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_CREW_ENABLED", "true")
    monkeypatch.setenv("MOCK_IMAGE_GENERATOR_ENABLED", "true")
    monkeypatch.setenv("MOCK_IMAGE_VISION_ANALYSIS_SOURCE", "claim_context")
    monkeypatch.setenv("MOCK_CREW_SEED", "42")
    # Reset adapter cache if needed
    yield
    # Cleanup
```

- [ ] Add `mock_crew` fixture
- [ ] Ensure it works with `temp_db`, `seeded_temp_db`, `claim_context`
- [ ] Add `mock_crew_with_images` variant that enables image generation (requires API key)

### 6.2 E2E Test with Mock Crew

**New file:** `tests/e2e/test_mock_crew_e2e.py`

- [ ] Test: submit claim with mock claimant, process through workflow, assert no real API calls (except optionally image gen)
- [ ] Test: follow-up flow – send_user_message → mock claimant responds → record_user_response
- [ ] Test: analyze_damage_photo with mock returns claim-consistent analysis

---

## Phase 7: Mock Document Generator (Optional)

**New file:** `src/claim_agent/mock_crew/document_generator.py`

- [ ] `generate_repair_estimate(claim_context: dict) -> dict` – JSON with line items, labor, parts, total
- [ ] `generate_damage_photo_url(claim_context: dict) -> str` – delegate to image generator
- [ ] Wire into tests that need claimant documents

---

## Phase 8: Mock Repair Shop, Third Party, Webhook (Optional)

Follow the same pattern:
- **Mock Repair Shop:** Intercept or stub responses when `send_user_message` targets `repair_shop`
- **Mock Third Party:** Intercept `send_demand_letter`, return configurable response
- **Mock Webhook:** Patch `dispatch_webhook` to append to a list; tests assert on list contents

---

## File Summary

| File | Action |
|------|--------|
| `src/claim_agent/config/settings_model.py` | Add MockCrewConfig, MockImageConfig |
| `src/claim_agent/config/settings.py` | Add get_mock_* helpers, vision adapter backend |
| `src/claim_agent/mock_crew/__init__.py` | Package init |
| `src/claim_agent/mock_crew/image_generator.py` | **OpenRouter image generation** |
| `src/claim_agent/mock_crew/vision_mock.py` | Mock vision analysis from claim context |
| `src/claim_agent/mock_crew/claimant.py` | Mock claimant submit + respond |
| `src/claim_agent/mock_crew/notifier.py` | Mock notifier intercept |
| `src/claim_agent/tools/vision_logic.py` | Wire mock vision branch |
| `src/claim_agent/notifications/user.py` | Wire mock notifier |
| `tests/conftest.py` | mock_crew fixture |
| `tests/e2e/test_mock_crew_e2e.py` | E2E tests |

---

## Implementation Order Checklist

1. [ ] **Phase 1** – Config (MockCrewConfig, MockImageConfig, VISION_ADAPTER)
2. [ ] **Phase 2** – Image generator (OpenRouter, prompt, save to disk)
3. [ ] **Phase 3** – Mock vision analysis + wire into vision_logic
4. [ ] **Phase 4** – Mock Claimant
5. [ ] **Phase 5** – Mock Notifier
6. [ ] **Phase 6** – Fixtures + E2E tests
7. [ ] **Phase 7** – Document generator (optional)
8. [ ] **Phase 8** – Repair shop, third party, webhook (optional)

---

## OpenRouter Image Generation – Implementation Notes

1. **Model selection:** Use `curl "https://openrouter.ai/api/v1/models?output_modality=image"` to get current models. Prefer a model that returns base64 in a documented format.
2. **Modalities:** Some models need `modalities: ["image"]` in the request. Check OpenRouter docs for your model.
3. **Rate limits:** Image generation can be slower and more expensive than text. Consider caching by (claim_id, damage_description hash) when seed is set.
4. **Fallback:** If OpenRouter fails, fall back to a placeholder (e.g., PIL-generated image with text overlay) so tests don't break.

---

## References

- [OpenRouter Image Generation Docs](https://openrouter.ai/docs/guides/overview/multimodal/image-generation)
- [OpenRouter Image Models](https://openrouter.ai/collections/image-models)
- [Mock Crew Design](mock-crew-design.md)
- [Mock Crew Requirements](mock-crew-requirements.md)
