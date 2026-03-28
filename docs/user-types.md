# User Types and Follow-up Agent

Formal user types enable structured human-in-the-loop flows beyond the adjuster review queue. The follow-up agent can interact with claimants, policyholders, repair shops, and other stakeholders to complete tasks, gather context, or ask clarifying questions.

## User Types

| User Type | Description | Example Use |
|-----------|-------------|-------------|
| `claimant` | Person who filed the claim | Request photos, clarify damage, confirm incident details |
| `policyholder` | Named insured on policy | Verify coverage, confirm vehicle usage |
| `adjuster` | Human reviewer | Escalation handback, approval/rejection |
| `repair_shop` | Body shop / repair facility | Confirm estimate, schedule repair, request supplement |
| `siu` | Special Investigations Unit | Fraud referral, investigation updates |
| `other` | Generic external party | Attorneys, medical providers, etc. |

## When to Use Each

- **claimant**: When the person who filed needs to provide additional information (photos, clarification, incident details). Common for `pending_info` flow.
- **policyholder**: When the named insured must verify coverage or confirm vehicle usage. Used in disputes and coverage verification.
- **repair_shop**: When coordinating with a body shop for estimates, supplements, or repair scheduling. Used in partial loss and supplemental flows.
- **siu**: When escalating fraud referrals or coordinating with Special Investigations Unit.
- **adjuster**: When handing back to human review or requesting approval.
- **other**: Catch-all for attorneys, medical providers, or other external parties.

## Follow-up Agent

The Follow-up Crew (`create_follow_up_crew`) has three agents:

1. **Outreach Planner** – Identifies which user type to contact and plans the request
2. **Message Composer** – Drafts and sends tailored outreach via `send_user_message`
3. **Response Processor** – Processes user responses via `record_user_response` and updates claim notes

### Tools

- `send_user_message` – Send a follow-up message to a user (claimant, policyholder, repair_shop, etc.)
- `record_user_response` – Record a user's response to a follow-up message
- `check_pending_responses` – Check for pending follow-ups awaiting response

### Integration with pending_info

When an adjuster calls `request_info` (status → `pending_info`), the follow-up agent can be triggered manually to:

1. Draft and send the request to the claimant
2. Wait for response (via webhook, API, or manual entry)
3. Process the response and update the claim

**API endpoints:**

- `POST /api/v1/claims/{claim_id}/follow-up/run` – Run the follow-up workflow with a task description
- `POST /api/v1/claims/{claim_id}/follow-up/record-response` – Record a user response (webhook or manual)
- `GET /api/v1/claims/{claim_id}/follow-up` – List follow-up messages for a claim

### Flow Example

```
Claim CLM-XXX → status: pending_info (adjuster requested photos)
    → POST /follow-up/run with task: "Gather photos of damage from claimant"
    → Follow-up agent: user type claimant
    → Composes: "Please upload photos of the damage to [link] or reply with..."
    → Sends via email/SMS (notify_user)
    → Response received (webhook or POST /follow-up/record-response)
    → ResponseProcessor parses, adds claim note, updates status
    → Workflow resumes or escalates
```

## Audit Trail

All follow-up interactions are logged:

- `follow_up_sent` – When a message is created and sent
- `follow_up_response` – When a user response is recorded

The `follow_up_messages` table stores message content, status, and response for full audit history.
