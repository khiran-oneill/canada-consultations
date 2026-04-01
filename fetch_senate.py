"""
Senate of Canada Committees — Active Studies Fetcher
=====================================================
Queries the Senate website's internal API for all committee studies and bills
currently underway in the 45th Parliament, 1st Session, filtered to those
referred in the last 30 days.

The Senate does not publish formal "call for briefs" deadlines the way the
House of Commons does. Instead, any Senate committee that is actively studying
a topic can receive written submissions at any time during the study.
To submit a brief, email: ctm@sen.parl.gc.ca (Senate Committees Directorate)
or contact the specific committee clerk listed on the committee's page.

Run it like this (after activating your virtual environment):
    python fetch_senate.py
"""

import re
import sys
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL    = "https://sencanada.ca"
SESSION     = "45-1"                  # 45th Parliament, 1st Session
SESSION_START = date(2025, 5, 26)     # Update this when a new session begins

STUDIES_API = f"{BASE_URL}/umbraco/surface/CommitteesAjax/GetTablePartialView"

# Only return studies referred within this many days (Order of Reference date).
RECENT_DAYS = 30

# Committees to exclude — purely administrative, not substantive
EXCLUDED_COMMITTEES = {
    "CIBA",   # Internal Economy, Budgets and Administration
    "SELE",   # Selection Committee
    "HRRH",   # Subcommittee on Human Resources (internal)
    "LTVP",   # Subcommittee on Long Term Vision and Plan
    "SEBS",   # Subcommittee on Senate Estimates and Committee Budgets
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; canada-consultations-bot/1.0; "
        "for personal research)"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_committee_acronym(href: str) -> str:
    """Extract committee acronym from a Senate URL like /en/committees/amad/"""
    m = re.search(r"/committees/([a-zA-Z]+)/?", href)
    return m.group(1).upper() if m else ""


def format_date(d: date) -> str:
    return d.strftime("%B %d, %Y")


# ── Main scraping logic ───────────────────────────────────────────────────────

def fetch_studies() -> list[dict]:
    """
    Call the Senate API and return studies referred in the last RECENT_DAYS days.
    Each item: { source, title, committee, acronym, oor_date, url, oor_label }
    """
    print(f"Fetching Senate committee studies (session {SESSION}) ...")
    try:
        resp = requests.get(
            STUDIES_API,
            params={
                "tableName":   "Studies",
                "committeeId": 0,
                "pageSize":    250,
                "fromDate":    SESSION_START.isoformat(),
                "toDate":      "",
                "session":     SESSION,
            },
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Error calling Senate API: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")
    raw_items = soup.find_all("div", class_="cmt-site_v2-studybills-table-study-item")
    print(f"Found {len(raw_items)} studies/bills in this session.\n")

    results = []
    today = date.today()

    for item in raw_items:

        # --- Title ----------------------------------------------------------
        title_tag = item.find(class_="cmt-site_v2-studybills-table-study-item-name")
        title = title_tag.get_text(" ", strip=True) if title_tag else "Untitled"

        # --- Committee name & link ------------------------------------------
        committee_div = item.find(class_="cmt-site_v2-studybills-table-study-item-committee")
        committee_link = committee_div.find("a") if committee_div else None
        committee_name = committee_link.get_text(strip=True) if committee_link else "Unknown"
        committee_href = committee_link["href"] if committee_link else ""
        acronym = get_committee_acronym(committee_href)

        # Skip purely administrative committees
        if acronym in EXCLUDED_COMMITTEES:
            continue

        # --- Order of Reference date ----------------------------------------
        oor_div = item.find(class_="cmt-site_v2-studybills-table-study-item-oof")
        oor_date = None
        oor_label = "No order of reference date"
        if oor_div:
            oor_text = oor_div.get_text(" ", strip=True)
            m = re.search(r"\d{4}-\d{2}-\d{2}", oor_text)
            if m:
                try:
                    oor_date = datetime.strptime(m.group(0), "%Y-%m-%d").date()
                    days_ago = (today - oor_date).days
                    oor_label = f"{format_date(oor_date)}  ({days_ago} days ago)"
                except ValueError:
                    pass

        # Clean committee URL
        clean_committee_url = re.sub(r"/#\?.*$", "/", committee_href)
        if not clean_committee_url.startswith("http"):
            clean_committee_url = BASE_URL + clean_committee_url

        studies_url = f"{BASE_URL}/en/committees/{acronym.lower()}/{SESSION}"

        results.append({
            "source":        "Senate of Canada Committees",
            "title":         title,
            "committee":     committee_name,
            "acronym":       acronym,
            "oor_date":      oor_date,
            "oor_label":     oor_label,
            "url":           studies_url,
            "committee_url": clean_committee_url,
        })

    # Keep only studies referred in the last RECENT_DAYS days
    results = [
        r for r in results
        if r["oor_date"] and (today - r["oor_date"]).days <= RECENT_DAYS
    ]

    # Sort: most recently referred first
    results.sort(key=lambda x: x["oor_date"], reverse=True)
    return results


# ── Backwards-compat alias ────────────────────────────────────────────────────
fetch = fetch_studies


# ── Output ────────────────────────────────────────────────────────────────────

def print_results(studies: list[dict]) -> None:
    if not studies:
        print("No active Senate committee studies found.")
        return

    today = date.today()
    print(f"\n{'=' * 72}")
    print(f"  SENATE OF CANADA -- ACTIVE COMMITTEE STUDIES ({SESSION})")
    print(f"  {len(studies)} studies referred in last {RECENT_DAYS} days")
    print(f"  To submit a brief: ctm@sen.parl.gc.ca")
    print(f"  Retrieved: {today.strftime('%B %d, %Y')}")
    print(f"{'=' * 72}\n")

    for i, s in enumerate(studies, start=1):
        print(f"[{i}] {s['title']}")
        print(f"    Committee        : {s['committee']} ({s['acronym']})")
        print(f"    Order of Ref.    : {s['oor_label']}")
        print(f"    Study page       : {s['url']}")
        print(f"    How to submit    : Email ctm@sen.parl.gc.ca — "
              f"mention study title and committee")
        print(f"    {'-' * 68}\n")

    print(f"Total: {len(studies)} studies referred in last {RECENT_DAYS} days.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    studies = fetch_studies()
    print_results(studies)
