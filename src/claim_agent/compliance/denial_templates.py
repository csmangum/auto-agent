"""State-specific denial letter templates.

Authoritative denial boilerplate for supported states lives in this module (Python).
Do not maintain a parallel JSON corpus for the same text—use :mod:`claim_agent.rag`
corpora for retrieval augmentation only, not as a second source of letter language.

Each state template provides:
- Regulatory references mandated by state law (e.g., California CCR, Texas TIC)
- State-specific appeal rights language
- Mandated regulatory body complaint procedure notices
- Required header / footer elements beyond generic UCSPA defaults

Supported states: California (CA), Florida (FL), New York (NY), Texas (TX), Georgia (GA).
Falls back to the generic template for unsupported or missing states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from claim_agent.rag.constants import normalize_state


@dataclass
class StateDenialTemplate:
    """Parameters that define a state-specific denial letter layout."""

    state: str
    jurisdiction: str
    """Two-letter abbreviation used in citations (e.g. CA, TX)."""
    regulation_reference: str
    """Primary regulation that governs written denials (printed in letter header)."""
    appeal_rights_text: str
    """Full appeal-rights paragraph required by state law."""
    complaint_procedure_text: str
    """Mandatory notice about filing a complaint with the state insurance regulator."""
    mandatory_disclosures: list[str] = field(default_factory=list)
    """Additional state-mandated disclosures appended to every denial letter."""
    header_notice: str = ""
    """Optional notice printed immediately below the denial title (e.g. language mandate)."""


# ---------------------------------------------------------------------------
# Per-state templates
# ---------------------------------------------------------------------------

_STATE_DENIAL_TEMPLATES: dict[str, StateDenialTemplate] = {
    "California": StateDenialTemplate(
        state="California",
        jurisdiction="CA",
        regulation_reference="California Code of Regulations, Title 10, Section 2695.7(g)",
        appeal_rights_text=(
            "APPEAL RIGHTS (California):\n"
            "You have the right to dispute this denial. You may:\n"
            "  1. Request a written explanation of the specific policy provisions relied upon.\n"
            "  2. Submit a written appeal to this company within 180 days of this notice.\n"
            "  3. File a complaint with the California Department of Insurance (CDI) at:\n"
            "     www.insurance.ca.gov  |  1-800-927-4357\n"
            "  4. Request further written explanation of the factual and policy basis for this denial.\n"
            "This notice is provided pursuant to CCR §2695.7(b)(3) and California Insurance Code §790.03."
        ),
        complaint_procedure_text=(
            "CALIFORNIA DEPARTMENT OF INSURANCE NOTICE:\n"
            "If you believe this claim has been wrongfully denied or handled unfairly, you may file a "
            "complaint with the California Department of Insurance (CDI):\n"
            "  Online: www.insurance.ca.gov/01-consumers/101-help/index.cfm\n"
            "  Phone:  1-800-927-HELP (4357)\n"
            "  TDD:    1-800-482-4833\n"
            "The CDI investigates complaints against insurance companies at no charge."
        ),
        mandatory_disclosures=[
            "Pursuant to CCR §2695.7(g), all grounds for this denial are stated herein. "
            "Any ground for denial not stated in this letter is waived.",
            "If you have retained legal counsel, please direct all communications through your attorney.",
        ],
        header_notice=(
            "This denial notice is issued in accordance with the California Fair Claims Settlement "
            "Practices Regulations (CCR Title 10, Chapter 5, Subchapter 7.5)."
        ),
    ),
    "Florida": StateDenialTemplate(
        state="Florida",
        jurisdiction="FL",
        regulation_reference="Florida Statutes Section 626.9541 and Florida Administrative Code Rule 69O-166",
        appeal_rights_text=(
            "APPEAL RIGHTS (Florida):\n"
            "You have the right to appeal this denial decision. You may:\n"
            "  1. Submit a written request for reconsideration to this company within 30 days.\n"
            "  2. File a complaint with the Florida Department of Financial Services (DFS) at:\n"
            "     www.myfloridacfo.com/Division/Consumers  |  1-877-693-5236\n"
            "  3. Pursue mediation or litigation as permitted under Florida law.\n"
            "This notice is provided pursuant to Fla. Stat. §627.70131 and §626.9541."
        ),
        complaint_procedure_text=(
            "FLORIDA DEPARTMENT OF FINANCIAL SERVICES NOTICE:\n"
            "If you believe your claim was handled improperly, contact the Florida Department of "
            "Financial Services, Division of Consumer Services:\n"
            "  Online: www.myfloridacfo.com/Division/Consumers\n"
            "  Phone:  1-877-693-5236 (toll-free in Florida)\n"
            "  Fax:    850-413-3089\n"
            "You also have the right to request an informal conference with this insurer before "
            "pursuing formal remedies."
        ),
        mandatory_disclosures=[
            "This denial is made in accordance with the terms and conditions of your policy as "
            "permitted under Florida Statutes Chapter 627.",
            "Florida law requires that this denial state all specific grounds. Grounds not stated "
            "herein cannot be asserted in any subsequent proceeding (Fla. Stat. §626.9541(1)(i)).",
        ],
    ),
    "New York": StateDenialTemplate(
        state="New York",
        jurisdiction="NY",
        regulation_reference=(
            "New York Insurance Law Section 3420(d) and 11 NYCRR Part 216 "
            "(Regulation 64 — Unfair Claims Settlement Practices)"
        ),
        appeal_rights_text=(
            "APPEAL RIGHTS (New York):\n"
            "You have the right to dispute this denial. Under New York law you may:\n"
            "  1. Submit a written request for reconsideration to this company within 60 days.\n"
            "  2. Request an external appeal through the New York State Department of Financial "
            "     Services (DFS) External Appeal Program within 45 days of this notice.\n"
            "  3. File a complaint with the DFS at: www.dfs.ny.gov  |  1-800-342-3736\n"
            "  4. Pursue arbitration or litigation as permitted under NY Insurance Law §3420.\n"
            "This notice is issued pursuant to 11 NYCRR §216.6 and NY Insurance Law §3420(d)(2)."
        ),
        complaint_procedure_text=(
            "NEW YORK DEPARTMENT OF FINANCIAL SERVICES NOTICE:\n"
            "If you believe this claim has been wrongfully denied, you may file a complaint with the "
            "New York State Department of Financial Services:\n"
            "  Online: www.dfs.ny.gov/complaint\n"
            "  Phone:  1-800-342-3736\n"
            "  Mail:   NYS Department of Financial Services, One Commerce Plaza, Albany, NY 12257\n"
            "The DFS Consumer Assistance Unit reviews complaints without charge."
        ),
        mandatory_disclosures=[
            "Pursuant to 11 NYCRR §216.6, this denial states all grounds upon which it is based. "
            "Coverage defenses not raised herein may be deemed waived.",
            "No-Fault/PIP denials are subject to additional requirements under 11 NYCRR Part 65.",
        ],
        header_notice=(
            "This denial notice is issued in accordance with New York Insurance Law §3420(d) and "
            "11 NYCRR Part 216 (Regulation 64)."
        ),
    ),
    "Texas": StateDenialTemplate(
        state="Texas",
        jurisdiction="TX",
        regulation_reference="Texas Insurance Code Chapter 542 (Prompt Payment of Claims), Subchapter B",
        appeal_rights_text=(
            "APPEAL RIGHTS (Texas):\n"
            "You have the right to dispute this denial. Under Texas law you may:\n"
            "  1. Submit additional information or a written appeal to this company at any time.\n"
            "  2. File a complaint with the Texas Department of Insurance (TDI) at:\n"
            "     www.tdi.texas.gov/consumer  |  1-800-252-3439\n"
            "  3. Contact the Office of Public Insurance Counsel (OPIC) at:\n"
            "     www.opic.texas.gov  |  512-322-4143\n"
            "  4. Pursue appraisal, mediation, or litigation as permitted under Texas law.\n"
            "Note: Under TIC §542.060, delayed payment may result in an 18% annual penalty "
            "plus attorney fees if a court finds coverage was wrongfully denied."
        ),
        complaint_procedure_text=(
            "TEXAS DEPARTMENT OF INSURANCE NOTICE:\n"
            "The Texas Department of Insurance (TDI) regulates insurance in Texas. If you believe "
            "your claim was handled improperly, contact TDI:\n"
            "  Online: www.tdi.texas.gov/consumer/complain.html\n"
            "  Phone:  1-800-252-3439\n"
            "  Mail:   Texas Department of Insurance, P.O. Box 149104, Austin, TX 78714-9104\n"
            "You may also contact the Office of Public Insurance Counsel (OPIC) at "
            "www.opic.texas.gov for free assistance."
        ),
        mandatory_disclosures=[
            "This denial is issued pursuant to Texas Insurance Code §542.056. The insurer has "
            "accepted or denied the claim not later than the 15th business day after receipt of "
            "all required information.",
            "Under TIC §542.060, an insurer that is liable for a claim and delays payment beyond "
            "the statutory period is liable for interest at 18% per annum plus attorney fees.",
        ],
        header_notice=(
            "This denial notice is issued pursuant to the Texas Prompt Payment of Claims Act "
            "(TIC Chapter 542, Subchapter B) and Texas DOI regulations."
        ),
    ),
    "Georgia": StateDenialTemplate(
        state="Georgia",
        jurisdiction="GA",
        regulation_reference="Georgia Insurance Code Title 33, Chapter 6 (Unfair Trade Practices)",
        appeal_rights_text=(
            "APPEAL RIGHTS (Georgia):\n"
            "You have the right to dispute this denial. Under Georgia law you may:\n"
            "  1. Submit a written request for reconsideration and any additional supporting "
            "     documentation to this company within 60 days of this notice.\n"
            "  2. File a complaint with the Georgia Office of Commissioner of Insurance (OCI) at:\n"
            "     www.oci.ga.gov  |  1-800-656-2298\n"
            "  3. Invoke the appraisal process if your policy provides for it.\n"
            "  4. Pursue litigation or alternative dispute resolution as permitted by Georgia law.\n"
            "This notice is provided pursuant to O.C.G.A. §33-6-34."
        ),
        complaint_procedure_text=(
            "GEORGIA OFFICE OF COMMISSIONER OF INSURANCE NOTICE:\n"
            "If you believe this claim was handled unfairly or in bad faith, you may contact the "
            "Georgia Office of Commissioner of Insurance (OCI):\n"
            "  Online: www.oci.ga.gov/ConsumerService/FileAComplaint.aspx\n"
            "  Phone:  1-800-656-2298\n"
            "  Mail:   Georgia Office of Commissioner of Insurance, Two Martin Luther King Jr. "
            "Drive, West Tower Suite 716, Atlanta, GA 30334\n"
            "The OCI reviews insurer conduct at no charge to consumers."
        ),
        mandatory_disclosures=[
            "This denial is issued in accordance with O.C.G.A. §33-6-34, which requires insurers "
            "to affirm or deny coverage within a reasonable time after proof of loss is submitted.",
            "Georgia law (O.C.G.A. §33-4-6) provides that an insurer that denies a claim in bad "
            "faith may be liable for the loss amount, plus up to 50% of the loss and attorney fees.",
        ],
    ),
}


def get_denial_template(state: str | None) -> StateDenialTemplate | None:
    """Return the state-specific denial letter template, or None if unsupported.

    Args:
        state: Full state name or two-letter abbreviation.

    Returns:
        :class:`StateDenialTemplate` for the given state, or ``None`` when the
        state is not supported or ``state`` is empty/``None``.
    """
    if not state or not str(state).strip():
        return None
    try:
        canonical = normalize_state(str(state).strip())
        return _STATE_DENIAL_TEMPLATES.get(canonical)
    except ValueError:
        return None


def render_denial_letter(
    claim_id: str,
    denial_reason: str,
    policy_provision: str,
    state: str | None = None,
    exclusion_citation: str | None = None,
    appeal_deadline: str | None = None,
    required_disclosures: str | None = None,
) -> str:
    """Render a denial letter using the state template when available.

    Falls back to the generic template for unsupported or missing states.

    Args:
        claim_id: Claim identifier.
        denial_reason: Clear, specific reason for the denial.
        policy_provision: Policy section/provision that applies.
        state: Loss state or jurisdiction (name or abbreviation).
        exclusion_citation: Optional specific exclusion language.
        appeal_deadline: Deadline for policyholder to appeal (overrides template text
            when provided; appended alongside the state-mandated appeal block).
        required_disclosures: Additional adjuster-supplied disclosures.

    Returns:
        Formatted denial letter text.
    """
    template = get_denial_template(state)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if template is None:
        return _render_generic(
            claim_id=claim_id,
            denial_reason=denial_reason,
            policy_provision=policy_provision,
            exclusion_citation=exclusion_citation,
            appeal_deadline=appeal_deadline,
            required_disclosures=required_disclosures,
            today=today,
        )

    return _render_state(
        template=template,
        claim_id=claim_id,
        denial_reason=denial_reason,
        policy_provision=policy_provision,
        exclusion_citation=exclusion_citation,
        appeal_deadline=appeal_deadline,
        required_disclosures=required_disclosures,
        today=today,
    )


# ---------------------------------------------------------------------------
# Internal rendering helpers
# ---------------------------------------------------------------------------


def _render_generic(
    claim_id: str,
    denial_reason: str,
    policy_provision: str,
    exclusion_citation: str | None,
    appeal_deadline: str | None,
    required_disclosures: str | None,
    today: str,
) -> str:
    lines = [
        "=" * 60,
        "CLAIM DENIAL NOTICE",
        "=" * 60,
        "",
        f"Claim ID: {claim_id}",
        f"Date: {today}",
        "",
        "Dear Policyholder,",
        "",
        "We have completed our review of your claim. After careful consideration of the policy "
        "terms and the circumstances of your claim, we must deny coverage for the following reason:",
        "",
        f"DENIAL REASON: {denial_reason}",
        "",
        f"APPLICABLE POLICY PROVISION: {policy_provision}",
    ]
    if exclusion_citation:
        lines.extend(["", f"EXCLUSION: {exclusion_citation}", ""])
    if appeal_deadline:
        lines.extend([
            "",
            "APPEAL RIGHTS:",
            f"You have the right to appeal this decision. "
            f"Your appeal must be received by {appeal_deadline}.",
            "",
        ])
    if required_disclosures:
        lines.extend(["", "REQUIRED NOTICES:", required_disclosures, ""])
    lines.extend([
        "If you have questions or wish to provide additional information, please contact us.",
        "",
        "Sincerely,",
        "Claims Department",
        "=" * 60,
    ])
    return "\n".join(lines)


def _render_state(
    template: StateDenialTemplate,
    claim_id: str,
    denial_reason: str,
    policy_provision: str,
    exclusion_citation: str | None,
    appeal_deadline: str | None,
    required_disclosures: str | None,
    today: str,
) -> str:
    lines = [
        "=" * 60,
        f"CLAIM DENIAL NOTICE — {template.state.upper()}",
        "=" * 60,
    ]
    if template.header_notice:
        lines.extend(["", template.header_notice])
    lines.extend([
        "",
        f"Regulatory Authority: {template.regulation_reference}",
        "",
        f"Claim ID: {claim_id}",
        f"Date: {today}",
        "",
        "Dear Policyholder,",
        "",
        "We have completed our review of your claim. After careful consideration of the applicable "
        f"{template.state} regulations and the terms and conditions of your policy, we must deny "
        "coverage for the following reason:",
        "",
        f"DENIAL REASON: {denial_reason}",
        "",
        f"APPLICABLE POLICY PROVISION: {policy_provision}",
    ])
    if exclusion_citation:
        lines.extend(["", f"EXCLUSION: {exclusion_citation}", ""])

    # State-mandated appeal rights block
    lines.extend(["", template.appeal_rights_text])

    # If a specific deadline is provided, append it after the state block
    if appeal_deadline:
        lines.extend([
            "",
            f"APPEAL DEADLINE: Your appeal must be received by {appeal_deadline}.",
        ])

    # State-mandated complaint procedure
    lines.extend(["", template.complaint_procedure_text])

    # State-mandated disclosures
    if template.mandatory_disclosures:
        lines.extend(["", "REQUIRED STATE DISCLOSURES:"])
        for disclosure in template.mandatory_disclosures:
            lines.extend([f"  • {disclosure}"])

    # Adjuster-supplied additional disclosures
    if required_disclosures:
        lines.extend(["", "ADDITIONAL NOTICES:", required_disclosures])

    lines.extend([
        "",
        "If you have questions regarding this decision or your policy, please contact us directly.",
        "",
        "Sincerely,",
        "Claims Department",
        "=" * 60,
    ])
    return "\n".join(lines)
