# Compliance & Policy Corpus Requirements

Requirements for a RAG corpus that provides prompt context and agentic search to all agents and crews. This document inventories what exists today, identifies gaps, and specifies the documents, regulations, and policy language each crew needs.

---

## 1. Current Corpus Inventory

### Policy Language (per-state policy terms, exclusions, definitions)

| State | File | Status |
|-------|------|--------|
| California | `data/california_auto_policy_language.json` | Complete |
| Texas | `data/texas_auto_policy_language.json` | Complete |
| Florida | `data/florida_auto_policy_language.json` | Complete |
| New York | `data/new_york_auto_policy_language.json` | Complete |
| Georgia | — | Gap (compliance JSON added; policy language file not yet) |
| New Jersey | — | Gap (corpus data file not created yet; state is in `SUPPORTED_STATES` / RAG) |
| Pennsylvania | — | Gap (corpus data file not created yet; state is in `SUPPORTED_STATES` / RAG) |
| Illinois | — | Gap (corpus data file not created yet; state is in `SUPPORTED_STATES` / RAG) |

### Compliance / Regulatory (statutes, regulations, deadlines, disclosures)

| State | File | Status |
|-------|------|--------|
| California | `data/california_auto_compliance.json` | Complete |
| Texas | `data/texas_auto_compliance.json` | Complete |
| Florida | `data/florida_auto_compliance.json` | Complete |
| New York | `data/new_york_auto_compliance.json` | Complete |
| Georgia | `data/georgia_auto_compliance.json` | Partial (diminished value / 17c; expand over time) |
| New Jersey | — | Gap (corpus data file not created yet; state is in `SUPPORTED_STATES` / RAG) |
| Pennsylvania | — | Gap (corpus data file not created yet; state is in `SUPPORTED_STATES` / RAG) |
| Illinois | — | Gap (corpus data file not created yet; state is in `SUPPORTED_STATES` / RAG) |

RAG and compliance tools accept all **eight** states in `SUPPORTED_STATES`: California, Texas, Florida, New York, Georgia, New Jersey, Pennsylvania, and Illinois. Compliance JSON files under `data/` named `*_auto_compliance.json` are ingested by the RAG chunker for states where those files exist (CA, TX, FL, NY, GA today). **New Jersey, Pennsylvania, and Illinois** are supported at the API/tool layer but do not yet have `data/<state>_auto_compliance.json` (or policy language) files—add those to match the first five states.

Compliance tools (`get_compliance_deadlines`, `get_required_disclosures`, `get_fraud_detection_guidance`, `get_repair_standards`, `get_total_loss_requirements`, `search_state_compliance`) return state-specific results when passed the appropriate state and corpus data is present for that state.

---

## 2. Required State Compliance Documents

Each state compliance file should mirror the California structure and cover the sections below. Sources are the actual statutes/regulations that need to be ingested.

### 2.1 Texas (`texas_auto_compliance.json`)

| Section | Primary Sources |
|---------|----------------|
| Fair Claims Settlement Practices | Texas Insurance Code (TIC) Chapter 542, Subchapter B — Prompt Payment of Claims (§542.051–542.061) |
| Total Loss Regulations | TIC §2301.009 (total loss threshold); 28 TAC §5.4104 (ACV, comparables, salvage deductions) |
| Time Limits & Deadlines | TIC §542.055 (15-day acknowledgment); §542.056 (acceptance/denial); §542.057–058 (payment + 18% penalty) |
| Required Disclosures | 28 TAC §5.4001–5.4005 (repair shop choice, parts, appraisal); TIC §1952.301 (rental) |
| UM/UIM Coverage | TIC §1952.101–.106 (UM/UIM mandatory offer); §1952.110 (stacking) |
| Anti-Fraud Provisions | TIC Chapter 701 (Insurance Fraud); Texas Penal Code §35.02; TIC §701.051 (SIU reporting) |
| Repair Standards | TIC §1952.301–.304 (shop choice); 28 TAC §5.4070 (parts, labor rate surveys); TIC §1952.303 (DRP disclosure) |
| Prohibited Practices / Good Faith | TIC §541.060 (unfair claims settlement); TIC §542.014 (bad faith liability) |
| Subrogation Rules | Texas common law (made-whole doctrine not followed — contractual subrogation prevails); TIC §1952.110 (UM setoff) |
| Rental Car Coverage | TIC §1952.301 (loss-of-use); 28 TAC §5.4001(b) |
| PIP / MedPay | TIC §1952.151–.159 (PIP — mandatory offer of $2,500 minimum; rejection requires signed form) |
| Comparative Fault | Texas Civil Practice & Remedies Code §33.001–.017 (modified comparative fault, 51% bar) |
| Statute of Limitations | CPRC §16.003 (2 years personal injury); §16.003 (2 years property damage); §16.004 (4 years breach of contract) |

### 2.2 Florida (`florida_auto_compliance.json`)

| Section | Primary Sources |
|---------|----------------|
| Fair Claims Settlement Practices | Florida Statutes (FS) §626.9541 (unfair claims practices); §626.9541(1)(i) (prohibited practices) |
| No-Fault / PIP | FS §627.730–.7405 (Motor Vehicle No-Fault Law); §627.736 (PIP benefits — $10K, 14-day rule, 80% medical, 60% lost wages) |
| Total Loss Regulations | FS §319.30 (total-loss threshold — 80% of ACV or owner-retained); FL Admin Code 69O-166 |
| Time Limits & Deadlines | FS §627.4265 (90-day claim filing); §627.426 (60-day Civil Remedy Notice); §627.70131 (90-day payment) |
| Required Disclosures | FS §627.7263 (windshield repair); §626.9743 (repair shop choice); §627.7288 (rental reimbursement) |
| UM/UIM Coverage | FS §627.727 (UM — mandatory; stacking/non-stacking); §627.727(1) (rejection waiver) |
| Anti-Fraud Provisions | FS §817.234 (insurance fraud); §626.989 (anti-fraud reporting); §626.9891 (SIU requirements) |
| Repair Standards | FS §626.9743 (shop choice); §501.976 (aftermarket parts disclosure); FL Admin Code 69O-166.031 |
| Prohibited Practices | FS §626.9541(1)(i) (16 enumerated unfair practices) |
| Subrogation Rules | Florida common law (made-whole doctrine applies); FS §768.76 (collateral source rule) |
| Rental Car Coverage | FS §627.7263 (loss-of-use for windshield); §627.7288 (rental reimbursement terms) |
| Bad Faith | FS §624.155 (statutory bad faith — Civil Remedy Notice required before suit) |
| Comparative Fault | FS §768.81 (modified comparative fault — 51% bar, effective 2023 tort reform) |
| Statute of Limitations | FS §95.11(3)(a) (4 years negligence — reduced to 2 years post-2024 HB 837); §95.11(2)(b) (5 years breach of contract) |

### 2.3 New York (`new_york_auto_compliance.json`)

| Section | Primary Sources |
|---------|----------------|
| Fair Claims Settlement Practices | NY Insurance Law (NYIL) §2601 (unfair claims settlement practices — 25 enumerated); 11 NYCRR 216 (Regulation 64) |
| No-Fault | NYIL Article 51 (Comprehensive Motor Vehicle Insurance Reparations Act); §5102 (basic economic loss — $50K); §5104 (serious injury threshold) |
| Total Loss Regulations | 11 NYCRR 216.7 (total loss settlement); NYIL §3411 (ACV, comparables); DMV salvage requirements |
| Time Limits & Deadlines | 11 NYCRR 216.4 (15 business days acknowledgment); 216.6 (30 calendar days settlement offer after investigation); NYIL §5106(a) (30-day no-fault payment) |
| Required Disclosures | 11 NYCRR 216.4(b) (claim form and instructions); 216.11 (claimant rights); NYIL §3411 (total-loss disclosures) |
| UM/UIM Coverage | NYIL §3420(f) (SUM — supplementary UM/UIM — mandatory $25K/$50K); 11 NYCRR 60-2 (Regulation 35-D) |
| Anti-Fraud Provisions | NY Penal Law §176.05–.30 (insurance fraud degrees); NYIL §405 (fraud warning statement); §409 (SIU reporting) |
| Repair Standards | NYIL §2610 (shop choice — Freedom of Choice); §2610(b) (aftermarket parts disclosure); General Business Law §398-e |
| Prohibited Practices | NYIL §2601 (25 prohibited acts); 11 NYCRR 216 (unfair settlement) |
| Subrogation Rules | NY common law (made-whole doctrine generally followed); CPLR §4545 (collateral source — adjusted since 2009) |
| Rental Car Coverage | NYIL §3411(g) (total-loss rental period); 11 NYCRR 216.7(b)(4) |
| No-Fault Arbitration | NYIL §5106 (mandatory arbitration for no-fault disputes); 11 NYCRR 65-4 (Regulation 68) |
| Comparative Fault | CPLR §1411 (pure comparative fault — same as California) |
| Statute of Limitations | CPLR §214(5) (3 years personal injury); CPLR §214(4) (3 years property damage); CPLR §213(2) (6 years breach of contract) |

---

## 3. Federal Regulations (All States)

These apply across every jurisdiction and are currently absent from the corpus entirely.

### 3.1 Privacy & Data Handling

| Regulation | Relevance | Crews Affected |
|------------|-----------|----------------|
| **HIPAA** (45 CFR Parts 160, 164) — Privacy Rule, Security Rule | Medical records handling, PHI storage, minimum necessary standard, authorization requirements | Bodily Injury, Medical Records Reviewer |
| **HITECH Act** (42 USC §17931–17940) | Breach notification, enhanced HIPAA enforcement | Bodily Injury |
| **Gramm-Leach-Bliley Act** (15 USC §6801–6809; Reg P — 12 CFR 1016) | Nonpublic personal financial information; privacy notices | All crews handling policyholder financial data |
| **FCRA** (15 USC §1681) | Consumer report usage in underwriting/claims; adverse action notices | Fraud Detection, Policy Verification |
| **State Privacy Laws** (CCPA/CPRA for CA, SHIELD Act for NY, TDPSA for TX) | PII handling, data minimization, consumer rights | All crews |

### 3.2 Medicare & Medicaid

| Regulation | Relevance | Crews Affected |
|------------|-----------|----------------|
| **Medicare Secondary Payer (MSP)** (42 USC §1395y(b)) | Mandatory reporting of settlements involving Medicare beneficiaries; conditional payment recovery | Bodily Injury, Settlement, Payment Distribution |
| **MMSEA Section 111 Reporting** (42 USC §1395y(b)(8)) | Electronic reporting of settlements/judgments to CMS | Settlement, Bodily Injury |
| **Medicare Set-Aside (MSA)** (CMS Workers' Comp MSA guidelines, adapted to liability) | Future medical cost allocation in settlements for Medicare-eligible claimants | Bodily Injury, Settlement Negotiator |
| **Medicaid Liens** (42 USC §1396k; state Medicaid recovery statutes) | State Medicaid agency recovery from settlement proceeds | Bodily Injury, Payment Distribution |

### 3.3 Fraud & Financial Crime

| Regulation | Relevance | Crews Affected |
|------------|-----------|----------------|
| **18 USC §1033–1034** (federal insurance fraud) | Criminal penalties for fraud in insurance business | Fraud Detection |
| **NICB Reporting Guidelines** | Voluntary but standard — reporting to National Insurance Crime Bureau | Fraud Detection |
| **State Fraud Bureau Reporting** (varies — e.g., CA CDI Fraud Division, TX DFR, FL DIFS, NY FBU) | Mandatory SIU referral and fraud reporting to state fraud bureaus | Fraud Detection, Escalation |

### 3.4 Collection & Recovery

| Regulation | Relevance | Crews Affected |
|------------|-----------|----------------|
| **FDCPA** (15 USC §1692) | If subrogation demand is treated as debt collection; prohibited practices | Subrogation (Demand Specialist, Recovery Tracker) |
| **State Collection Laws** | Licensing, fee caps, demand letter requirements | Subrogation |
| **Arbitration Compacts** (Arbitration Forums Inc. rules) | Inter-company arbitration for subrogation disputes | Subrogation |

### 3.5 Vehicle Title & Salvage

| Regulation | Relevance | Crews Affected |
|------------|-----------|----------------|
| **NMVTIS** (49 USC §30502; 28 CFR Part 25) | National Motor Vehicle Title Information System — reporting totaled/salvage vehicles | Salvage, Title Specialist |
| **State DMV Salvage/Branding Rules** (varies by state) | Title branding (salvage, rebuilt, flood), transfer timelines, VIN verification | Salvage, Title Specialist |

**Codebase:** NMVTIS is automated via `NMVTISAdapter` (mock/stub), triggered from `record_dmv_salvage_report` and final salvage dispositions; acknowledgments are stored in `total_loss_metadata`. A real deployment must connect `NMVTIS_ADAPTER` to the designated data provider. See [Adapters](adapters.md#nmvtisadapter).

### 3.6 Electronic Transactions

| Regulation | Relevance | Crews Affected |
|------------|-----------|----------------|
| **ESIGN Act** (15 USC §7001) | Electronic signatures/records validity | Settlement, Denial/Coverage |
| **UETA** (state adoptions) | State-level electronic transaction validity | Settlement, Denial/Coverage |

---

## 4. Crew-by-Crew Corpus Needs

### 4.1 Router Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| Claim type classification rules | Medium | Currently in skill; could be RAG-backed for multi-state variations |
| State-specific total-loss thresholds | High | Threshold varies: CA (repair + salvage > ACV), TX (varies by insurer), FL (80% ACV), NY (75% ACV) |
| Bodily injury routing criteria | Medium | Serious-injury threshold (NY), PIP exhaustion rules (FL, NY) |

### 4.2 New Claim Crew (Intake, Policy Verification, Assignment)

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| State intake/acknowledgment requirements | High | Deadlines differ: CA 15 cal days, TX 15 cal days, NY 15 bus days, FL varies |
| Anti-fraud notice requirements | Medium | Mandatory fraud warning language varies by state |
| Required proof-of-claim forms | Medium | State-specific required forms |
| Policy form definitions by state | Low | Already in policy language files |

### 4.3 Duplicate Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| No specific compliance docs needed | — | Duplicate detection is operational, not regulatory |

### 4.4 Total Loss Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| State total-loss thresholds and formulas | **Critical** | Different formulas per state |
| ACV valuation requirements (comparables, documentation) | **Critical** | CA: ≥2 comparables within 100mi; states vary |
| Salvage deduction and owner-retention disclosures | High | State-specific disclosure language |
| Sales tax / fee reimbursement rules | High | CA CIC 11580.26; varies by state |
| Gap insurance interaction | Medium | When total-loss payout < loan balance |
| NMVTIS reporting | Medium | Federal salvage reporting |

### 4.5 Fraud Detection Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| State insurance fraud statutes | **Critical** | CA CIC 1871–1879.8; TX TIC Ch 701; FL FS 817.234; NY Penal Law 176 |
| SIU formation and reporting requirements | **Critical** | State-mandated SIU, reporting timelines (CA 60 days, etc.) |
| Fraud indicators / red flags (CDI/NICB guidelines) | High | Staged accident indicators, organized fraud ring patterns |
| Federal fraud statutes (18 USC 1033) | High | Federal prosecution thresholds |
| EUO (Examination Under Oath) rules | High | When/how to compel EUO; state-specific provisions |
| Material misrepresentation standards | Medium | Burden of proof, intent requirements |
| Anti-fraud warning statement language | Medium | Exact statutory language per state |

### 4.6 Partial Loss Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| State repair standards and shop-choice rights | **Critical** | CA CIC 758.5; varies per state |
| OEM vs. aftermarket parts rules | **Critical** | State disclosure and consent requirements |
| Labor rate dispute resolution | High | Prevailing rate surveys, state requirements |
| DRP (Direct Repair Program) disclosure | High | Financial arrangement disclosures |
| Supplemental authorization rules | High | Prompt inspection requirements (CA CCR 2695.8) |
| Repair warranty requirements | Medium | DRP warranty mandates |

### 4.7 Rental Reimbursement Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| State rental/loss-of-use rules | **Critical** | Period, class, daily limits, third-party vs first-party |
| Rental disclosure requirements | High | CA DISC-006; state equivalents |
| Comparable vehicle class definitions | Medium | Industry standards vs state mandates |

### 4.8 Settlement Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| State settlement documentation requirements | **Critical** | Release language, execution rules, minor settlement rules |
| Payment timing regulations | **Critical** | CA 30 days, TX with 18% penalty, FL 90 days, NY 30 days |
| Lienholder and loss-payee payment rules | High | Payment order, notification requirements |
| Structured settlement rules | Medium | For large BI settlements |
| Records retention requirements | Medium | CA 5 years (CCR 2695.3); varies by state |
| ESIGN/UETA electronic settlement | Medium | Electronic release validity |

### 4.9 Subrogation Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| State comparative/contributory fault rules | **Critical** | Pure comparative (CA, NY), modified (TX 51%, FL 51%), contributory (MD, VA, NC, DC, AL) |
| Made-whole doctrine by state | **Critical** | CA follows; TX does not; FL follows; NY generally follows |
| Demand letter requirements | High | Content, timing, method of service |
| Subrogation statutes of limitation | High | Often same as underlying tort SOL |
| Arbitration Forums / inter-company arbitration | High | Industry rules for inter-insurer disputes |
| Anti-subrogation rules | Medium | Cannot subrogate against own insured |
| FDCPA applicability | Medium | If demand is treated as debt collection |

### 4.10 Salvage Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| State salvage title and branding rules | **Critical** | Salvage, rebuilt, flood, junk branding rules |
| DMV title transfer procedures by state | **Critical** | Forms, timelines, fees |
| NMVTIS reporting requirements | High | Federal — report within 30 days |
| Owner retention rules and disclosures | High | Salvage deduction, title implications |
| Environmental / disposal regulations | Medium | Hazardous material disposal for scrap |
| Auction house licensing | Low | State-specific auctioneer/dealer licensing |

### 4.11 Denial / Coverage Dispute Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| State denial notice requirements | **Critical** | Content, timing, format, appeal rights |
| Unfair claims settlement practices acts (per state) | **Critical** | CA CIC 790.03; TX TIC 541.060; FL FS 626.9541; NY NYIL 2601 |
| Coverage interpretation rules | High | Contra proferentem, reasonable expectations, ambiguity |
| DOI complaint procedures by state | High | Filing process, response deadlines, escalation paths |
| Bad faith standards and remedies by state | High | Compensatory, punitive, emotional distress, attorney fees |
| Appraisal clause standards | Medium | Triggering, selection of appraisers, umpire |

### 4.12 Supplemental Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| Supplemental damage inspection requirements | **Critical** | CA CCR 2695.8 — prompt inspection and authorization |
| State repair authorization rules | High | When re-authorization is needed |
| Parts and labor standards for supplementals | Medium | Same standards as original; OEM/aftermarket rules apply |

### 4.13 Bodily Injury Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| State serious-injury thresholds | **Critical** | NY §5104 verbal threshold; FL PIP exhaustion rules |
| PIP / No-Fault coverage rules | **Critical** | FL $10K/14-day/80%/60%; NY $50K basic economic loss |
| HIPAA compliance for medical records | **Critical** | Authorization, minimum necessary, PHI handling |
| Medicare Secondary Payer rules | **Critical** | Conditional payment recovery, MMSEA Section 111 |
| State medical lien statutes | High | Hospital liens, physician liens, Medicaid liens |
| BI settlement calculation frameworks | High | Special damages multiplier, per diem, state-specific norms |
| Minor settlement / guardian rules | High | Court approval requirements by state |
| Wrongful death statutes | High | Eligible claimants, damages caps, SOL |
| Pain and suffering damages rules | Medium | State caps (if any), calculation methods |
| Independent Medical Examination (IME) rules | Medium | When insurer can compel IME |
| Medical provider fee schedules | Medium | FL, NY no-fault fee schedules |
| Structured settlement regulations | Medium | IRC §104(a)(2); state structured settlement protection acts |

### 4.14 Dispute Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| State dispute resolution procedures | **Critical** | Appraisal, arbitration, mediation, DOI complaint |
| UM/UIM arbitration rules | **Critical** | CA CIC 11580.2(f); state equivalents |
| Labor rate dispute mechanisms | High | Rate surveys, prevailing rate determination |
| Diminished value claim rules | High | First-party vs third-party; state positions |
| DOI complaint process and response deadlines | High | CA 21 days; varies by state |

### 4.15 Reopened Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| Reopening standards by state | High | When a settled claim can be reopened |
| Statute of limitations for reopened claims | High | SOL for newly discovered damage |
| Release language and reopening implications | Medium | Whether signed release bars reopening |

### 4.16 Escalation Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| Bad faith standards by state | **Critical** | What constitutes bad faith in each jurisdiction |
| DOI complaint triggers and response requirements | High | When to involve regulatory counsel |
| SIU referral thresholds and procedures | High | Mandatory vs discretionary referral criteria |
| Regulatory complaint timelines | High | Response windows, documentation requirements |
| Legal hold and preservation obligations | Medium | When litigation is reasonably anticipated |

### 4.17 Human Review Handback Crew

| Corpus Need | Priority | Notes |
|-------------|----------|-------|
| No specific compliance docs needed beyond what upstream crews use | — | Handback applies upstream crew's compliance context |

---

## 5. Corpus Structure Recommendations

### 5.1 Document Types

Each document in the corpus should be tagged with metadata for filtering:

```json
{
  "metadata": {
    "state": "Texas",
    "jurisdiction": "TX",
    "data_type": "compliance",
    "domain": "fair_claims",
    "version": "2025.1",
    "last_updated": "2025-01-31",
    "sources": ["Texas Insurance Code", "28 TAC Title 28"]
  }
}
```

Allowed values for `data_type`: `compliance`, `policy_language`, `federal_regulation`, `industry_standard`.

Allowed values for `domain`: `fair_claims`, `total_loss`, `fraud`, `repair`, `rental`, `subrogation`, `salvage`, `bodily_injury`, `pip_nofault`, `settlement`, `denial`, `dispute`, `privacy`, `medicare`, `collection`, `title_salvage`, `electronic`.

### 5.2 Recommended Corpus Files

#### Tier 1 — Critical (blocks multi-state operation)

| File | Description |
|------|-------------|
| `data/texas_auto_compliance.json` | TX regulatory compliance (mirrors CA structure) |
| `data/florida_auto_compliance.json` | FL regulatory compliance (mirrors CA structure + PIP/no-fault) |
| `data/new_york_auto_compliance.json` | NY regulatory compliance (mirrors CA structure + no-fault) |
| `data/federal_privacy_regulations.json` | HIPAA, GLBA, FCRA, state privacy laws |
| `data/federal_medicare_msp.json` | MSP, MMSEA Section 111, MSA guidelines, Medicaid lien rules |

#### Tier 2 — High (needed for crew correctness)

| File | Description |
|------|-------------|
| `data/state_fraud_statutes.json` | Per-state fraud statutes, SIU rules, reporting requirements, federal 18 USC 1033 |
| `data/state_bodily_injury_rules.json` | Serious-injury thresholds, PIP rules, BI settlement frameworks, wrongful death, minor settlements |
| `data/state_subrogation_rules.json` | Made-whole doctrine, comparative fault, inter-company arbitration, SOL for recovery |
| `data/state_salvage_title_rules.json` | DMV title transfer, salvage branding, NMVTIS, owner retention |
| `data/state_bad_faith_standards.json` | Bad faith elements, remedies, notable case law, DOI complaint procedures |
| `data/state_settlement_rules.json` | Payment timing, release requirements, lienholder rules, records retention, e-signature |

#### Tier 3 — Medium (enhances quality)

| File | Description |
|------|-------------|
| `data/state_repair_standards.json` | Multi-state repair shop choice, parts rules, labor rates, DRP, supplemental |
| `data/state_rental_coverage_rules.json` | Multi-state rental/loss-of-use, class, duration, disclosure |
| `data/state_dispute_resolution.json` | Appraisal, arbitration, DOI complaints, diminished value |
| `data/federal_collection_laws.json` | FDCPA, state collection licensing, arbitration compacts |
| `data/state_comparative_fault.json` | Pure vs modified comparative, contributory negligence, caps |
| `data/state_statute_of_limitations.json` | Per-state SOL for PI, PD, contract, bad faith, subrogation |
| `data/federal_electronic_transactions.json` | ESIGN, UETA, state adoption notes |
| `data/industry_standards.json` | NICB reporting, ISO claim forms, Arbitration Forums rules, CCC/Mitchell valuation |

> **Indexing note:** The current RAG loader only globs `*_policy_language.json` and `*_compliance.json` when building the vector store. Files such as `data/federal_privacy_regulations.json`, `data/federal_medicare_msp.json`, `data/state_fraud_statutes.json`, `data/state_statute_of_limitations.json`, `data/federal_electronic_transactions.json`, and `data/industry_standards.json` will **not** be indexed unless you either (a) rename them to follow the existing naming convention (e.g., `*_policy_language.json` / `*_compliance.json`), or (b) extend `chunk_*_data()` and `_build_index()` in the retriever to include these additional filenames.

---

## 6. Chunking Considerations for New Document Types

The existing chunker handles `policy_language` and `compliance` data types. Adding new data types requires two steps: (1) extending the retriever's file-discovery and indexing step (`_build_index()`) to include the new filenames, and (2) implementing a matching `chunk_*_data()` function for each new data type. Without both changes, new files will not be chunked or added to the vector store.

| Data Type | Chunking Strategy |
|-----------|------------------|
| `federal_regulation` | By regulation section → subsection → provision (similar to compliance) |
| `case_law_summary` | By case → holding → relevance (short summaries, not full opinions) |
| `industry_standard` | By standard → provision → guidance |
| `state_comparison` | By topic → state-by-state provisions (enables cross-state queries) |

### New Metadata Fields

```
domain       — topical domain (see 5.1 list above)
applies_to   — list of crew names this content is relevant to
federal      — boolean, true for federal regulations
effective_date — when the regulation took effect
```

---

## 7. Source Acquisition Notes

### Authoritative Sources

| Source Type | Where to Get |
|-------------|--------------|
| State insurance codes | State legislature websites (leginfo.legislature.ca.gov, statutes.capitol.texas.gov, etc.) |
| State admin codes / regulations | Secretary of State regulation databases (e.g., CA OAL, TX SOS, FL DOS, NY DOS) |
| CDI / TDI / FLDFS / NYDFS bulletins | Department of Insurance websites |
| Federal statutes | uscode.house.gov, congress.gov |
| Federal regulations (CFR) | ecfr.gov |
| CMS guidelines (MSA, Section 111) | cms.gov/medicare-coordination |
| NICB guidelines | nicb.org |
| Arbitration Forums rules | arbfile.org |

### Maintenance

- Compliance data should be versioned (`version` field) and reviewed at least annually or when legislative sessions end.
- Each file should include `last_updated` and `sources` for traceability.
- State regulatory bulletins and emergency orders should be added as supplements when issued.

---

## 8. Priority Roadmap

### Phase 1 — Multi-State Compliance Parity

Create `texas_auto_compliance.json`, `florida_auto_compliance.json`, `new_york_auto_compliance.json` mirroring all sections in the California file. This unblocks every compliance tool for TX/FL/NY.

### Phase 2 — Federal Regulations

Add `federal_privacy_regulations.json` and `federal_medicare_msp.json`. This is required for the Bodily Injury crew to function correctly and for all crews to handle PII properly.

### Phase 3 — Domain-Specific Deep Dives

Add `state_fraud_statutes.json`, `state_bodily_injury_rules.json`, `state_subrogation_rules.json`, `state_salvage_title_rules.json`, `state_bad_faith_standards.json`, `state_settlement_rules.json`. These directly improve crew decision quality.

### Phase 4 — Completeness & Cross-Referencing

Add remaining Tier 3 files. Extend chunker for new data types. Add cross-state comparison documents for agents that need to apply the correct state's rules.

---

## 9. Crew → Corpus Cross-Reference Matrix

| Crew | Policy Language | State Compliance | Federal Privacy | Medicare/MSP | Fraud Statutes | BI Rules | Subrogation | Salvage/Title | Bad Faith | Settlement | Repair | Rental | Dispute | Fault/SOL |
|------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Router | x | x | | | | x | | | | | | | | x |
| New Claim | x | x | | | | | | | | | | | | |
| Duplicate | | | | | | | | | | | | | | |
| Total Loss | x | x | | | | | | x | | x | | | | |
| Fraud Detection | | x | | | **x** | | | | | | | | | |
| Partial Loss | x | x | | | | | | | | | **x** | | | |
| Rental | x | x | | | | | | | | | | **x** | | |
| Settlement | x | x | | x | | | | | | **x** | | | | |
| Subrogation | | x | | | | | **x** | | | | | | | **x** |
| Salvage | | x | | | | | | **x** | | | | | | |
| Denial/Coverage | x | x | | | | | | | **x** | | | | **x** | |
| Supplemental | x | x | | | | | | | | | **x** | | | |
| Bodily Injury | x | x | **x** | **x** | | **x** | | | | x | | | | x |
| Dispute | x | x | | | | | | | x | | x | | **x** | |
| Reopened | x | x | | | | | | | | | | | | x |
| Escalation | | x | | | x | | | | **x** | | | | | |

**Bold** = primary/critical dependency. `x` = secondary/reference dependency.
