# Settlement Specialist Skill

## Role
Settlement Workflow Overview

## Goal
Describe the shared settlement workflow that runs after payout-ready total loss and partial loss crews. This file documents the overall settlement phase; the live implementation is split across documentation, payment distribution, and closure specialists.

## Backstory
Settlement is now a reusable post-workflow phase. The shared crew standardizes documentation, payment distribution, and closure across claim types so payout-ready claims follow one final settlement path.

## Tools
- `generate_report` - Used by the documentation and closure specialists
- `generate_claim_id` - Used when workflow outputs are missing a claim reference
- `calculate_payout` - Used by the payment distribution specialist for verification on total loss claims
- `escalate_claim` - Used when settlement review reveals fraud or compliance issues

## Settlement Process

### 1. Gather Settlement Components
Collect all required information:
- Claim ID and policy number
- Claimant information
- Vehicle information (VIN, Year/Make/Model)
- Damage assessment summary
- Valuation details
- Payout calculation breakdown

### 2. Settlement Report Sections

#### Executive Summary
- Claim number and date of loss
- Type of loss (Total Loss)
- Settlement amount
- Payment recipient(s)

#### Claim Details
- Claimant name and contact
- Policy number and coverage type
- Date of incident
- Location of incident
- Description of loss

#### Vehicle Information
- Year, Make, Model, Trim
- VIN
- Mileage at time of loss
- Pre-accident condition
- Title status

#### Damage Assessment
- Summary of damage
- Total loss determination rationale
- Photos/documentation reference

#### Valuation Summary
- Actual Cash Value
- Valuation source(s)
- Adjustments applied
- Final ACV determination

#### Payout Breakdown
- ACV
- Additions (tax, fees)
- Deductions (deductible, prior damage)
- Net settlement amount
- Payment distribution

#### Terms and Conditions
- Title transfer requirements
- Salvage retention options (if applicable)
- Release and settlement agreement
- Payment timeline

### 3. Settlement Options

#### Standard Settlement
- Insurer takes possession of vehicle
- Full ACV payout
- Insured surrenders title

#### Owner Retention
- Insured keeps salvage vehicle
- Salvage value deducted from payout
- Salvage title issued to insured
- Calculation: Net Payout - Salvage Value

### 4. Required Authorizations

Before finalizing:
- [ ] Damage assessment verified
- [ ] Valuation approved
- [ ] Payout calculation reviewed
- [ ] Policy coverage confirmed
- [ ] Fraud check completed
- [ ] Lienholder notification (if applicable)

### 5. Claim Closure Steps

1. Generate final settlement report
2. Obtain insured's acceptance
3. Process settlement agreement
4. Issue payment(s)
5. Update claim status to CLOSED
6. Archive documentation
7. Initiate subrogation (if applicable)

### 6. Post-Settlement Tasks

#### Subrogation
If third party at fault:
- Document liability evidence
- Calculate subrogation potential
- Refer to recovery unit

#### Salvage Disposition
- Notify salvage vendor
- Arrange vehicle pickup
- Track salvage sale

#### Regulatory Reporting
- State DMV notification
- Total loss reporting
- NICB notification (if applicable)

## Report Template Structure

```
SETTLEMENT REPORT
=================
Claim #: [CLAIM_ID]
Date: [CURRENT_DATE]

SUMMARY
-------
Claim Type: Total Loss
Settlement Amount: $[NET_PAYOUT]
Status: Approved for Payment

CLAIMANT
--------
Name: [CLAIMANT_NAME]
Policy: [POLICY_NUMBER]

VEHICLE
-------
[YEAR] [MAKE] [MODEL]
VIN: [VIN]

VALUATION
---------
Actual Cash Value: $[ACV]
Source: [VALUATION_SOURCE]

SETTLEMENT CALCULATION
---------------------
ACV:           $[ACV]
+ Tax:         $[TAX]
+ Fees:        $[FEES]
- Deductible:  $[DEDUCTIBLE]
= Net Payout:  $[NET_PAYOUT]

PAYMENT DISTRIBUTION
-------------------
[RECIPIENT]: $[AMOUNT]

AUTHORIZATION
-------------
Approved by: [SYSTEM/ADJUSTER]
Date: [APPROVAL_DATE]
```

## Output Format
Provide settlement report with:
- `claim_id`: Unique claim identifier
- `claim_type`: "Total Loss"
- `status`: "Settled" / "Closed"
- `summary`: Brief narrative summary
- `payout_amount`: Net settlement figure
- `settlement_date`: Date of settlement
- `payment_details`: Recipient(s) and amounts
- `documentation`: List of attached documents
- `next_steps`: Any remaining actions (subrogation, salvage)
