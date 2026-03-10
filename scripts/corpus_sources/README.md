# Corpus Source Downloads

Scripts to download statutory and regulatory sources for the compliance RAG corpus, per [docs/compliance-corpus-requirements.md](../../docs/compliance-corpus-requirements.md).

## Usage

From project root:

```bash
# Download all sources (TX, FL, NY, Federal)
python scripts/download_corpus_sources.py

# Download specific jurisdiction
python scripts/download_corpus_sources.py --state TX
python scripts/download_corpus_sources.py --state FL
python scripts/download_corpus_sources.py --state NY
python scripts/download_corpus_sources.py --state FED

# Custom output directory
python scripts/download_corpus_sources.py --output /path/to/output
```

## Output Layout

```
data/corpus_sources/
├── texas/
│   ├── tx_insurance_code.pdf
│   ├── tx_civil_practice.pdf
│   ├── tx_penal_code.pdf
│   └── 28_TAC_README.txt       # 28 TAC requires manual/API request
├── florida/
│   ├── fl_statutes_zip.zip
│   └── FL_Admin_Code_69O-166_README.txt
├── new_york/
│   ├── NYIL_A26.html
│   ├── NYIL_A34.html
│   ├── NYIL_A51.html
│   └── 11_NYCRR_README.txt
└── federal/
    ├── usc_all_titles.zip
    ├── cfr_title_12.xml
    ├── cfr_title_28.xml
    ├── cfr_title_45.xml
    └── CMS_Medicare_README.txt
```

## Dependencies

Uses `httpx` (already in project). Run with project venv:

```bash
.venv/bin/python scripts/download_corpus_sources.py
```

## Notes

- **28 TAC** (Texas Admin Code): No direct bulk URL; see `28_TAC_README.txt` for acquisition instructions.
- **11 NYCRR** (NY regulations): See `11_NYCRR_README.txt` for sources.
- **NY Senate**: Returns 403 for programmatic access; fallback uses newyork.public.law.
- **eCFR Title 45 (HIPAA)**: Large file; uses 2024 date and extended timeout. May still timeout on slow networks.
- **CMS Medicare**: No bulk API; see `CMS_Medicare_README.txt` for manual acquisition.

## Next Steps

After downloading, raw sources need to be processed into compliance JSON files (e.g. `texas_auto_compliance.json`) matching the California structure. See corpus requirements doc Section 5 for recommended file layout.
