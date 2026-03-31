"""
Canada.ca Federal Consultations Fetcher
========================================
Downloads the open government CSV of all federal consultations and
filters it to show only those currently open for public input.

The data comes from the Open Government Portal — no HTML scraping needed.
CSV source: https://open.canada.ca/static/current_consultations_open.csv

Run it like this (after activating your virtual environment):
    python fetch_canada_ca.py
"""

import csv
import io
import sys
import requests
from datetime import date, datetime

# ── Configuration ─────────────────────────────────────────────────────────────

CSV_URL = "https://open.canada.ca/static/current_consultations_open.csv"

# Status codes used in the CSV
STATUS_OPEN    = "O"   # open for public input right now
STATUS_PLANNED = "P"   # upcoming — not yet open

# Include planned consultations in the output so you can prepare in advance.
# Set to False if you only want currently-open ones.
INCLUDE_PLANNED = False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language":           "en-CA,en;q=0.9",
    "Accept-Encoding":           "gzip, deflate, br",
    "Connection":                "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def format_date(date_str: str) -> str:
    """Convert '2026-03-30' to 'March 30, 2026'. Returns original if unparseable."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    except (ValueError, TypeError):
        return date_str or "Not specified"


def deadline_label(row: dict) -> str:
    """Build a human-readable deadline string from the CSV row."""
    end = row.get("end_date", "").strip()
    if not end:
        return "No deadline listed"
    try:
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
        days_left = (end_date - date.today()).days
        if days_left < 0:
            return f"{format_date(end)}  (closed {abs(days_left)} days ago)"
        elif days_left == 0:
            return f"{format_date(end)}  (closes TODAY)"
        else:
            return f"{format_date(end)}  ({days_left} days remaining)"
    except ValueError:
        return end


def trim(text: str, max_chars: int = 400) -> str:
    """Trim a string to max_chars, appending '...' if truncated."""
    text = text.strip()
    if len(text) > max_chars:
        return text[:max_chars - 3] + "..."
    return text


def status_label(code: str) -> str:
    return {"O": "Open", "P": "Planned (not yet open)", "C": "Closed"}.get(code, code)


# ── Main logic ────────────────────────────────────────────────────────────────

def fetch_consultations() -> list[dict]:
    """
    Download the CSV and return a list of open (and optionally planned)
    consultations, each as a dictionary with normalised fields.
    """
    print(f"Downloading consultation data from Open Government Portal ...")
    try:
        resp = requests.get(CSV_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Error downloading CSV: {e}")

    # The CSV is UTF-8 encoded
    reader = csv.DictReader(io.StringIO(resp.text))

    results = []
    for row in reader:
        status = row.get("status", "").strip()

        # Filter: only open (and optionally planned)
        if status == "C":
            continue
        if status == STATUS_PLANNED and not INCLUDE_PLANNED:
            continue

        title       = row.get("title_en", "").strip() or "Untitled consultation"
        description = row.get("description_en", "").strip()
        url         = row.get("profile_page_en", "").strip()
        # Department names in the CSV contain both English and French separated by " | "
        # e.g. "Agriculture and Agri-Food Canada | Agriculture et Agroalimentaire Canada"
        # We only want the English portion.
        department  = row.get("owner_org_title", "").strip().split(" | ")[0]
        start_raw   = row.get("start_date", "").strip()
        end_raw     = row.get("end_date", "").strip()

        # Parse end_date for sorting and freshness filtering
        try:
            end_date_obj = datetime.strptime(end_raw, "%Y-%m-%d").date()
            still_open = (end_date_obj >= date.today())
        except (ValueError, TypeError):
            end_date_obj = date(9999, 12, 31)
            still_open = True   # no deadline listed — assume still open

        # Skip anything whose deadline has already passed, regardless of status tag.
        # The government's CSV sometimes leaves expired "Open" entries in the feed,
        # and "Planned" entries occasionally have past end dates too.
        if not still_open:
            continue

        results.append({
            "source":        "Canada.ca -- Federal Consultations",
            "title":         title,
            "department":    department or "Federal government",
            "summary":       trim(description) if description else "(No description provided)",
            "deadline":      deadline_label(row),
            "start_date":    format_date(start_raw),
            "status":        status_label(status),
            "url":           url or "https://www.canada.ca/en/government/system/consultations/consultingcanadians.html",
            "_end_date_obj": end_date_obj,   # used for sorting, not displayed
        })

    # Sort: open first, then planned; within each group, soonest deadline first
    results.sort(key=lambda x: (0 if x["status"] == "Open" else 1, x["_end_date_obj"]))

    n_open    = sum(1 for r in results if r["status"] == "Open")
    n_planned = sum(1 for r in results if r["status"] != "Open")
    print(f"Found {len(results)} active consultation(s) "
          f"({n_open} open with future deadlines, {n_planned} planned).\n")
    return results


# ── Output ────────────────────────────────────────────────────────────────────

def print_results(consultations: list[dict]) -> None:
    if not consultations:
        print("No open or planned federal consultations found.")
        return

    print(f"{'=' * 72}")
    print(f"  CANADA.CA -- FEDERAL CONSULTATIONS (OPEN & PLANNED)")
    print(f"  Retrieved: {date.today().strftime('%B %d, %Y')}")
    print(f"{'=' * 72}\n")

    for i, c in enumerate(consultations, start=1):
        print(f"[{i}] {c['title']}")
        print(f"    Status     : {c['status']}")
        print(f"    Department : {c['department']}")
        print(f"    Started    : {c['start_date']}")
        print(f"    Deadline   : {c['deadline']}")
        print(f"    Summary    : {c['summary']}")
        print(f"    Link       : {c['url']}")
        print(f"    {'-' * 68}\n")

    print(f"Total: {len(consultations)} consultation(s) shown.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    consultations = fetch_consultations()
    print_results(consultations)
