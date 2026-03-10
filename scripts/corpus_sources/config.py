"""Configuration for corpus source downloads.

Sources are defined per docs/compliance-corpus-requirements.md Section 7.
"""

from pathlib import Path

# Output directory for raw downloaded sources (relative to project root)
OUTPUT_DIR = Path("data/corpus_sources")

# --- Texas (TIC, 28 TAC) ---
TX_SOURCES = [
    {
        "id": "tx_insurance_code",
        "name": "Texas Insurance Code",
        "url": "https://statutes.capitol.texas.gov/Docs/SDocs/INSURANCECODE.pdf",
        "format": "pdf",
        "sections": ["TIC Ch 542", "TIC Ch 701", "TIC §2301.009", "TIC §1952.301-304", "TIC §541.060", "TIC §542.014"],
    },
    {
        "id": "tx_civil_practice",
        "name": "Texas Civil Practice & Remedies Code",
        "url": "https://statutes.capitol.texas.gov/Docs/SDocs/CPRC.pdf",
        "format": "pdf",
        "sections": ["CPRC §33.001-017", "CPRC §16.003", "CPRC §16.004"],
    },
    {
        "id": "tx_penal_code",
        "name": "Texas Penal Code",
        "url": "https://statutes.capitol.texas.gov/Docs/SDocs/PENAL.pdf",
        "format": "pdf",
        "sections": ["Texas Penal Code §35.02"],
    },
]

# 28 TAC - Texas Admin Code (insurance rules) - no direct bulk URL; individual chapter requests
# Title 28 = Insurance. Part 1 = TDI. Chapter 5 = Subchapter 7 (Property and Casualty)
TX_TAC_NOTE = (
    "28 TAC (Texas Administrative Code) Title 28 Part 1 is available at "
    "https://texreg.sos.state.tx.us - requires manual or API request per chapter. "
    "Relevant: §5.4001-5.4005, §5.4070, §5.4104."
)

# --- Florida ---
FL_SOURCES = [
    {
        "id": "fl_statutes_zip",
        "name": "Florida Statutes (full download)",
        "url": "https://www.leg.state.fl.us/Statutes/FLLawDL2025.zip",
        "format": "zip",
        "sections": ["FS Ch 626", "FS Ch 627", "FS Ch 624", "FS Ch 817", "FS Ch 768", "FS Ch 319", "FS Ch 95"],
    },
]

# Alternative: individual chapter HTML (if zip requires auth or changes)
FL_STATUTE_BASE = "https://www.leg.state.fl.us/Statutes/index.cfm"

# --- New York ---
NY_SOURCES = [
    {
        "id": "ny_insurance_law",
        "name": "New York Insurance Law",
        "url": "https://public.leginfo.state.ny.us/lawssrch.cgi?NVLWO:",
        "format": "html",
        "note": "NYIL available at public.leginfo.state.ny.us; may need per-article fetch",
    },
]

# NY Consolidated Laws - alternative sources
NY_INSURANCE_LAW_BASE = "https://www.nysenate.gov/legislation/laws/ISC"
NY_CRR_BASE = "https://govt.westlaw.com/nycrr"  # 11 NYCRR (Regulation 64, etc.)

# --- Federal ---
# USC: Bulk zip from House OLRC (release point may change; check download page)
USC_BULK_ZIP_URL = "https://uscode.house.gov/download/releasepoints/us/pl/119/73not60/xml_uscAll@119-73not60.zip"

FEDERAL_SOURCES = [
    {
        "id": "usc_all_titles",
        "name": "USC All Titles (bulk XML)",
        "url": USC_BULK_ZIP_URL,
        "format": "zip",
        "sections": ["15 USC (GLBA, FCRA, FDCPA, ESIGN)", "18 USC §1033-1034", "42 USC (MSP, Medicaid, HITECH)"],
    },
    {
        "id": "cfr_title_45",
        "name": "CFR Title 45 (Public Welfare) - HIPAA",
        "url": "https://www.ecfr.gov/api/versioner/v1/full/2024-01-01/title-45.xml",
        "format": "xml",
        "sections": ["45 CFR Parts 160, 164 (HIPAA Privacy, Security)"],
        "note": "Uses 2024 date; 2025 may timeout (Title 45 is large)",
    },
    {
        "id": "cfr_title_12",
        "name": "CFR Title 12 (Regulation P - GLBA)",
        "url": "https://www.ecfr.gov/api/versioner/v1/full/2025-01-01/title-12.xml",
        "format": "xml",
        "sections": ["12 CFR 1016 (Reg P)"],
    },
    {
        "id": "cfr_title_28",
        "name": "CFR Title 28 (NMVTIS)",
        "url": "https://www.ecfr.gov/api/versioner/v1/full/2025-01-01/title-28.xml",
        "format": "xml",
        "sections": ["28 CFR Part 25 (NMVTIS)"],
    },
]

# US Code - House OLRC provides bulk zip; individual titles via download page
# See https://uscode.house.gov/download/download.shtml
USCODE_DOWNLOAD_PAGE = "https://uscode.house.gov/download/download.shtml"

# eCFR API - full title XML (date format: YYYY-MM-DD)
# https://www.ecfr.gov/reader-aids/ecfr-developer-resources/rest-api-interactive-documentation
ECFR_API_BASE = "https://www.ecfr.gov/api/versioner/v1/full"

# CMS Medicare - no bulk API; manual or scrape
CMS_MSP_URL = "https://www.cms.gov/medicare-coordination-benefits-recovery"
CMS_SECTION_111_URL = "https://www.cms.gov/medicare-coordination-benefits-recovery/mandatory-insurance-reporting"
