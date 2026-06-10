"""
scripts/fetch_pagasa/pagasa_ingestor.py
Semi-automated PAGASA data ingestion workflow for APA-CIS.

Since PAGASA has no public machine-readable API, this module provides:
  1. Structured PDF inbox processor (for manually downloaded PAGASA PDFs)
  2. Web scraping of public PAGASA pages (farm weather, 10-day, ENSO)
  3. Standardized output format for integration with indicator engine
  4. Template for future API integration when PAGASA grants access

IMPORTANT: Always verify PAGASA data against official publications.
This module is intended to assist, not replace, official PAGASA advisories.

DA RFO 02 — APA-CIS Climate Information Service
"""

import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.utils import (
    PROJECT_ROOT,
    load_config,
    load_json,
    log_etl_event,
    retry_get,
    save_json,
    setup_logger,
    today_pht,
)

logger = setup_logger(__name__, "pagasa_ingestor.log")
cfg = load_config()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. WEB SCRAPING — PAGASA PUBLIC PAGES
#    Note: Only scrapes publicly available text/data.
#    Respects robots.txt and PAGASA terms of service.
# ═══════════════════════════════════════════════════════════════════════════════

PAGASA_URLS = {
    "farm_weather": "https://www.pagasa.dost.gov.ph/agri-weather",
    "ten_day": "https://www.pagasa.dost.gov.ph/ten-day-regional-agri-weather",
    "enso": "https://www.pagasa.dost.gov.ph/climate/el-nino-la-nina/monitoring",
    "enso_advisories": "https://www.pagasa.dost.gov.ph/climate/el-nino-la-nina/advisories",
    "climate_monitor": "https://www.pagasa.dost.gov.ph/climate/climate-monitoring",
    "typhoon": "https://www.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin",
    "typhoon_agriculture": "https://www.pagasa.dost.gov.ph/tropical-cyclone/tropical-cyclone-warning-for-agriculture",
}

REGION2_IDENTIFIERS = [
    "Region II", "Region 2", "Cagayan Valley",
    "Cagayan", "Isabela", "Nueva Vizcaya", "Quirino", "Batanes",
    "II", "02",
]


def scrape_pagasa_page(url: str, page_name: str) -> Optional[str]:
    """
    Fetch raw HTML text from a PAGASA public page.
    Returns page text content for further parsing.
    """
    resp = retry_get(url, retries=2, delay=5.0, timeout=30, logger=logger)
    if resp is None:
        logger.warning(f"Could not fetch {page_name} from {url}")
        return None

    # Save raw HTML for audit trail
    raw_dir = PROJECT_ROOT / cfg["paths"]["raw_pagasa"] / today_pht().strftime("%Y/%m")
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / f"{page_name}_{today_pht().isoformat()}.html"
    with open(raw_file, "w", encoding="utf-8") as f:
        f.write(resp.text)
    logger.info(f"Saved raw HTML → {raw_file}")

    return resp.text


def extract_region2_text(html_text: str) -> List[str]:
    """
    Extract paragraphs/sentences mentioning Cagayan Valley / Region II
    from PAGASA page HTML (simple text extraction, no JS rendering).
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text, "html.parser")

        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
    except ImportError:
        # Fallback: strip HTML tags with regex
        text = re.sub(r"<[^>]+>", " ", html_text)

    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or len(line) < 10:
            continue
        if any(ident.lower() in line.lower() for ident in REGION2_IDENTIFIERS):
            lines.append(line)

    return lines


def parse_enso_status(html_text: str) -> Dict:
    """
    Parse PAGASA ENSO status page for current classification.

    Returns:
        {
            "enso_phase": "el_nino" | "la_nina" | "neutral",
            "enso_strength": "moderate" | "strong" | "weak" | None,
            "advisory_text": str,
            "source": "pagasa_enso_page",
            "as_of": date string,
        }
    """
    result = {
        "enso_phase": "unknown",
        "enso_strength": None,
        "advisory_text": "",
        "source": "pagasa_enso_page",
        "as_of": today_pht().isoformat(),
    }

    if not html_text:
        return result

    # Look for ENSO keywords
    text_lower = html_text.lower()

    if "el niño" in text_lower or "el nino" in text_lower:
        result["enso_phase"] = "el_nino"
    elif "la niña" in text_lower or "la nina" in text_lower:
        result["enso_phase"] = "la_nina"
    elif "neutral" in text_lower:
        result["enso_phase"] = "neutral"

    # Strength
    if "strong" in text_lower:
        result["enso_strength"] = "strong"
    elif "moderate" in text_lower:
        result["enso_strength"] = "moderate"
    elif "weak" in text_lower:
        result["enso_strength"] = "weak"

    # Extract Region 2 specific text
    region2_lines = extract_region2_text(html_text)
    if region2_lines:
        result["advisory_text"] = " ".join(region2_lines[:5])

    return result


def parse_farm_weather_forecast(html_text: str) -> Dict:
    """
    Parse PAGASA Farm Weather Forecast page for Region 2 content.

    Returns structured forecast summary for Cagayan Valley.
    Note: Full parsing requires JS rendering (Selenium/Playwright);
    this function handles static HTML content only.
    """
    result = {
        "source": "pagasa_farm_weather",
        "as_of": today_pht().isoformat(),
        "region2_forecast": [],
        "raw_text_extracted": "",
        "parse_method": "static_html",
        "needs_review": True,  # Always flag for human review
    }

    if not html_text:
        return result

    region2_lines = extract_region2_text(html_text)
    result["region2_forecast"] = region2_lines[:20]
    result["raw_text_extracted"] = "\n".join(region2_lines)

    return result


def fetch_live_pagasa_data() -> Dict:
    """
    Attempt to fetch current PAGASA data from public pages.
    Returns a combined result dict.
    """
    output = {
        "as_of": today_pht().isoformat(),
        "enso": {},
        "farm_weather": {},
        "scrape_status": {},
    }

    # Try ENSO page
    enso_html = scrape_pagasa_page(PAGASA_URLS["enso"], "enso")
    if enso_html:
        output["enso"] = parse_enso_status(enso_html)
        output["scrape_status"]["enso"] = "success"
    else:
        output["scrape_status"]["enso"] = "failed"
        output["enso"] = _get_enso_fallback()

    # Try farm weather page
    fw_html = scrape_pagasa_page(PAGASA_URLS["farm_weather"], "farm_weather")
    if fw_html:
        output["farm_weather"] = parse_farm_weather_forecast(fw_html)
        output["scrape_status"]["farm_weather"] = "success"
    else:
        output["scrape_status"]["farm_weather"] = "failed"

    return output


def _get_enso_fallback() -> Dict:
    """Return last known ENSO status from file if live fetch fails."""
    fallback_path = PROJECT_ROOT / cfg["paths"]["raw_pagasa"] / "enso_status.json"
    saved = load_json(fallback_path)
    if saved:
        saved["source"] = "pagasa_cached"
        saved["cache_note"] = "Live fetch failed; using cached value"
        return saved
    # Ultimate fallback: neutral
    return {
        "enso_phase": "neutral",
        "enso_strength": None,
        "advisory_text": "ENSO status unavailable. Monitor PAGASA advisories.",
        "source": "default_fallback",
        "as_of": today_pht().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PDF INBOX PROCESSOR
#    Drop PAGASA PDFs (10-day agri-weather, monthly outlook, bulletins)
#    into data/raw/pagasa/ and this processor will extract text from them.
# ═══════════════════════════════════════════════════════════════════════════════

def process_pdf_inbox() -> List[Dict]:
    """
    Process any unprocessed PAGASA PDFs in the inbox directory.
    Extracts text and saves structured JSON output.

    PDF types handled:
    - 10-day regional agri-weather
    - Monthly agro-climatic review
    - Typhoon bulletins
    - ENSO advisories

    Returns list of processed file records.
    """
    inbox = PROJECT_ROOT / cfg["paths"]["raw_pagasa"]
    processed_dir = inbox / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    processed_index_path = inbox / "processed_files.json"
    processed_index = load_json(processed_index_path) or []
    processed_names = {r["filename"] for r in processed_index}

    results = []

    pdf_files = list(inbox.glob("*.pdf")) + list(inbox.glob("*.PDF"))
    if not pdf_files:
        logger.info("No PDFs found in inbox.")
        return results

    for pdf_path in pdf_files:
        if pdf_path.name in processed_names:
            logger.debug(f"Already processed: {pdf_path.name}")
            continue

        logger.info(f"Processing: {pdf_path.name}")
        result = extract_pdf_text(pdf_path)

        if result:
            # Save extracted text as JSON
            out_path = processed_dir / f"{pdf_path.stem}.json"
            save_json(result, out_path)

            record = {
                "filename": pdf_path.name,
                "processed_at": datetime.utcnow().isoformat(),
                "doc_type": result.get("doc_type", "unknown"),
                "output_path": str(out_path),
                "region2_paragraphs": len(result.get("region2_content", [])),
            }
            processed_index.append(record)
            results.append(record)
            logger.info(f"  → Extracted {record['region2_paragraphs']} Region 2 paragraphs")

    # Update index
    if results:
        save_json(processed_index, processed_index_path)

    return results


def extract_pdf_text(pdf_path: Path) -> Optional[Dict]:
    """
    Extract text content from a PAGASA PDF.
    Requires PyMuPDF (fitz) or pdfplumber — install separately.
    """
    result = {
        "filename": pdf_path.name,
        "doc_type": _classify_pdf_name(pdf_path.name),
        "extracted_at": datetime.utcnow().isoformat(),
        "full_text": "",
        "region2_content": [],
        "source": "pagasa_pdf",
    }

    # Try PyMuPDF first (faster)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text())
        result["full_text"] = "\n".join(pages_text)
        result["parse_method"] = "pymupdf"
        doc.close()
    except ImportError:
        # Fallback: pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(str(pdf_path)) as pdf:
                result["full_text"] = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
            result["parse_method"] = "pdfplumber"
        except ImportError:
            logger.error(
                "Neither PyMuPDF nor pdfplumber is installed. "
                "Run: pip install PyMuPDF pdfplumber"
            )
            return None

    # Extract Region 2 relevant paragraphs
    region2_lines = []
    for line in result["full_text"].split("\n"):
        line = line.strip()
        if len(line) < 10:
            continue
        if any(ident.lower() in line.lower() for ident in REGION2_IDENTIFIERS):
            region2_lines.append(line)

    result["region2_content"] = region2_lines

    # Parse specific fields based on document type
    doc_type = result["doc_type"]
    if doc_type == "ten_day_agri_weather":
        result["parsed"] = parse_ten_day_text(result["full_text"])
    elif doc_type == "monthly_outlook":
        result["parsed"] = parse_monthly_outlook_text(result["full_text"])
    elif doc_type == "enso_advisory":
        result["parsed"] = _parse_enso_from_text(result["full_text"])

    return result


def _classify_pdf_name(filename: str) -> str:
    """Classify PAGASA PDF by filename pattern."""
    fname_lower = filename.lower()
    if "10-day" in fname_lower or "10day" in fname_lower or "tenday" in fname_lower:
        return "ten_day_agri_weather"
    if "monthly" in fname_lower or "agroclimatic" in fname_lower:
        return "monthly_outlook"
    if "enso" in fname_lower or "el-nino" in fname_lower or "la-nina" in fname_lower:
        return "enso_advisory"
    if "typhoon" in fname_lower or "bulletin" in fname_lower or "tc-" in fname_lower:
        return "typhoon_bulletin"
    return "unknown"


def parse_ten_day_text(text: str) -> Dict:
    """
    Parse 10-day agri-weather advisory text for Region 2 content.
    Extracts rainfall outlook, temperature ranges, and agri-advisories.
    """
    parsed = {
        "outlook_period": None,
        "region2_rainfall_outlook": [],
        "region2_temperature": [],
        "region2_agri_advisories": [],
    }

    # Look for date ranges (e.g., "June 11-20, 2026")
    date_pattern = r"(\w+\s+\d+[-–]\d+,?\s*\d{4})"
    dates = re.findall(date_pattern, text)
    if dates:
        parsed["outlook_period"] = dates[0]

    # Extract Region 2 lines
    in_region2 = False
    for line in text.split("\n"):
        line = line.strip()
        if any(id_ in line for id_ in ["Region II", "Cagayan Valley", "REGION II"]):
            in_region2 = True
        elif re.match(r"Region (I[^I]|V|X)", line):
            in_region2 = False  # Another region started

        if in_region2 and line:
            if any(w in line.lower() for w in ["rain", "mm", "rainfall"]):
                parsed["region2_rainfall_outlook"].append(line)
            elif any(w in line.lower() for w in ["temperature", "°c", "celsius"]):
                parsed["region2_temperature"].append(line)
            elif any(w in line.lower() for w in
                     ["plant", "harvest", "spray", "fertil", "irrigat", "advise"]):
                parsed["region2_agri_advisories"].append(line)

    return parsed


def parse_monthly_outlook_text(text: str) -> Dict:
    """Parse monthly agro-climatic review for Region 2 outlook."""
    parsed = {
        "forecast_period": None,
        "enso_classification": None,
        "region2_outlook": [],
        "region2_anomaly": [],
    }

    # ENSO classification
    for phase in ["El Niño", "La Niña", "Neutral", "El Nino", "La Nina"]:
        if phase.lower() in text.lower():
            parsed["enso_classification"] = phase
            break

    # Extract Region 2 content
    region2_lines = []
    for line in text.split("\n"):
        line = line.strip()
        if any(id_ in line for id_ in REGION2_IDENTIFIERS):
            region2_lines.append(line)

    parsed["region2_outlook"] = region2_lines[:15]
    return parsed


def _parse_enso_from_text(text: str) -> Dict:
    """Parse ENSO advisory text."""
    text_lower = text.lower()
    phase = "neutral"
    if "el niño" in text_lower or "el nino" in text_lower:
        phase = "el_nino"
    elif "la niña" in text_lower or "la nina" in text_lower:
        phase = "la_nina"

    strength = None
    for s in ["strong", "moderate", "weak"]:
        if s in text_lower:
            strength = s
            break

    return {
        "enso_phase": phase,
        "enso_strength": strength,
        "source_text_snippet": text[:500],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. MANUAL ENTRY TEMPLATE
#    For CIS staff to manually enter PAGASA 10-day advisory data
# ═══════════════════════════════════════════════════════════════════════════════

def create_manual_entry_template() -> Dict:
    """
    Create a blank template for manual entry of PAGASA advisories.
    CIS staff fills this after reviewing official PAGASA publications.
    Saved to data/raw/pagasa/manual_entry_template.json
    """
    today = today_pht().isoformat()
    template = {
        "_instructions": (
            "Fill this template based on the latest PAGASA advisories for Region 2. "
            "Save as 'manual_entry_YYYY-MM-DD.json' and run the ingestor."
        ),
        "entry_date": today,
        "entered_by": "",
        "source_document": "",
        "source_url": "",
        "enso": {
            "phase": "",  # "el_nino" | "la_nina" | "neutral"
            "strength": "",  # "weak" | "moderate" | "strong"
            "advisory_text": "",
        },
        "seasonal_outlook": {
            "forecast_period": "",  # e.g., "June–August 2026"
            "rainfall_outlook": "",  # "below_normal" | "near_normal" | "above_normal"
            "temperature_outlook": "",
            "narrative": "",
        },
        "ten_day_forecast": {
            "period_start": "",  # YYYY-MM-DD
            "period_end": "",
            "review_status": "draft",  # draft | reviewed | approved
            "cagayan": {"outlook": "", "rainfall_range_mm": "", "agri_advisory": ""},
            "isabela": {"outlook": "", "rainfall_range_mm": "", "agri_advisory": ""},
            "nueva_vizcaya": {"outlook": "", "rainfall_range_mm": "", "agri_advisory": ""},
            "quirino": {"outlook": "", "rainfall_range_mm": "", "agri_advisory": ""},
            "batanes": {"outlook": "", "rainfall_range_mm": "", "agri_advisory": ""},
        },
        "typhoon": {
            "active": False,
            "name": "",
            "bulletin_number": "",
            "issued_at": "",
            "source_url": "",
            "signal_levels": {
                "Batanes": 0,
                "Cagayan": 0,
                "Isabela": 0,
                "Nueva Vizcaya": 0,
                "Quirino": 0,
            },
        },
    }

    template_path = (
        PROJECT_ROOT / cfg["paths"]["raw_pagasa"] / "manual_entry_template.json"
    )
    save_json(template, template_path)
    logger.info(f"Manual entry template created → {template_path}")
    return template


def ingest_manual_entry(entry_path: Path) -> Optional[Dict]:
    """
    Ingest a completed manual entry file and integrate it with
    the indicator and advisory pipeline.
    """
    entry = load_json(entry_path)
    if not entry:
        logger.error(f"Could not load manual entry from {entry_path}")
        return None

    # Validate required fields
    required = ["entry_date", "entered_by", "source_document"]
    for field in required:
        if not entry.get(field):
            logger.warning(f"Manual entry missing field: {field}")

    # Save to standardized PAGASA output
    output_path = (
        PROJECT_ROOT / cfg["paths"]["raw_pagasa"]
        / f"pagasa_data_{entry.get('entry_date', today_pht().isoformat())}.json"
    )
    latest_path = PROJECT_ROOT / cfg["paths"]["raw_pagasa"] / "pagasa_current.json"
    save_json(entry, output_path)
    save_json(entry, latest_path)
    logger.info(f"Manual entry ingested → {output_path}")

    log_etl_event(
        source="pagasa_manual_entry",
        run_date=entry.get("entry_date", today_pht().isoformat()),
        records_fetched=1,
        records_valid=1,
        status="success",
        message=f"Manual entry by {entry.get('entered_by')} from {entry.get('source_document')}",
    )

    return entry


# ═══════════════════════════════════════════════════════════════════════════════
# 4. UNIFIED PAGASA DATA OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════

def get_pagasa_current() -> Dict:
    """
    Return the best available PAGASA data:
    1. Most recent manual entry (if today or within 10 days)
    2. Live scrape attempt
    3. Cached fallback

    This is the function called by the indicator and advisory engines.
    """
    pagasa_dir = PROJECT_ROOT / cfg["paths"]["raw_pagasa"]

    # Check for recent manual entries
    manual_entries = sorted(
        pagasa_dir.glob("pagasa_data_*.json"), reverse=True
    )

    if manual_entries:
        latest = load_json(manual_entries[0])
        if latest:
            entry_date = latest.get("entry_date", "")
            try:
                entry_d = date.fromisoformat(entry_date)
                if (today_pht() - entry_d).days <= 10:
                    logger.info(f"Using manual entry from {entry_date}")
                    latest["data_source"] = "manual_entry"
                    return latest
            except ValueError:
                pass

    # Attempt live scrape
    logger.info("No recent manual entry; attempting live PAGASA scrape...")
    live_data = fetch_live_pagasa_data()

    # Save for cache
    cache_path = pagasa_dir / "enso_status.json"
    if live_data.get("enso"):
        save_json(live_data["enso"], cache_path)

    return live_data


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def run() -> None:
    logger.info("=== PAGASA Data Ingestor ===")

    # Create template if it doesn't exist
    template_path = PROJECT_ROOT / cfg["paths"]["raw_pagasa"] / "manual_entry_template.json"
    if not template_path.exists():
        create_manual_entry_template()
        logger.info("Created manual entry template for CIS staff.")

    # Process any PDFs in inbox
    pdf_results = process_pdf_inbox()
    if pdf_results:
        logger.info(f"Processed {len(pdf_results)} PAGASA PDFs")

    # Attempt live data fetch
    pagasa_data = get_pagasa_current()

    # Save combined output for pipeline consumption
    output_path = (
        PROJECT_ROOT / cfg["paths"]["raw_pagasa"]
        / f"pagasa_current_{today_pht().isoformat()}.json"
    )
    latest_path = PROJECT_ROOT / cfg["paths"]["raw_pagasa"] / "pagasa_current.json"
    save_json(pagasa_data, output_path)
    save_json(pagasa_data, latest_path)

    logger.info("=== PAGASA ingestor complete ===")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PAGASA Data Ingestor")
    parser.add_argument("--create-template", action="store_true",
                        help="Create manual entry template")
    parser.add_argument("--ingest-entry", type=str, default=None,
                        help="Path to completed manual entry JSON file")
    args = parser.parse_args()

    if args.create_template:
        create_manual_entry_template()
        print("Template created in data/raw/pagasa/manual_entry_template.json")
    elif args.ingest_entry:
        result = ingest_manual_entry(Path(args.ingest_entry))
        if result:
            print(f"Ingested: {result.get('entry_date')} by {result.get('entered_by')}")
    else:
        run()
