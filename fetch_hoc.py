"""
House of Commons Committees — Calls for Briefs Fetcher
=======================================================
Scrapes the ourcommons.ca "Participate" page to find every committee study
that is currently accepting written submissions, then retrieves the deadline
from each study's activity page.

Run it like this (after activating your virtual environment):
    python fetch_hoc.py
"""

import re
import sys
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime
from dateutil.parser import parse as parse_date

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL      = "https://www.ourcommons.ca"
PARTICIPATE   = f"{BASE_URL}/Committees/en/Participate"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; canada-consultations-bot/1.0; "
        "for personal research)"
    )
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_soup(url: str) -> BeautifulSoup | None:
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [warning] Could not fetch {url}: {e}", file=sys.stderr)
        return None


def parse_deadline(text: str) -> tuple[str, date | None]:
    """
    Look for a date in a deadline string such as:
      'Submit a brief before 11:59 p.m. (EDT) on Sunday, March 15, 2026'
      'Written submissions ... until Thursday, April 30, 2026, at 11:59 p.m.'
    Returns (human_readable_string, date_object_or_None).
    """
    # Try to find a date pattern like "March 15, 2026" or "April 30, 2026"
    date_pattern = re.search(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4}",
        text, re.IGNORECASE
    )
    if date_pattern:
        raw = date_pattern.group(0).replace(",", "")
        try:
            d = parse_date(raw).date()
            days_left = (d - date.today()).days
            if days_left < 0:
                suffix = f"(closed {abs(days_left)} days ago)"
            elif days_left == 0:
                suffix = "(closes TODAY)"
            else:
                suffix = f"({days_left} days remaining)"
            return f"{d.strftime('%B %d, %Y')}  {suffix}", d
        except (ValueError, OverflowError):
            pass
    return "Deadline not specified — check original page", None


# ── Main scraping logic ───────────────────────────────────────────────────────

def get_study_links() -> list[dict]:
    """
    Fetch the Participate page and collect all links to study activity pages.
    Returns a list of dicts: { 'committee', 'study_url', 'title' }
    """
    print(f"Fetching participation page: {PARTICIPATE}")
    soup = get_soup(PARTICIPATE)
    if soup is None:
        raise RuntimeError("Could not load the Participate page.")

    studies = []
    seen = set()

    # Study links look like: /committees/en/FINA/StudyActivity?studyActivityId=13385942
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(
            r"/committees/en/([A-Z]+)/StudyActivity\?studyActivityId=(\d+)",
            href, re.IGNORECASE
        )
        if not m:
            continue
        committee = m.group(1).upper()
        activity_id = m.group(2)
        full_url = BASE_URL + href if href.startswith("/") else href

        if full_url in seen:
            continue
        seen.add(full_url)

        title = a.get_text(" ", strip=True) or f"{committee} study"
        studies.append({
            "committee":   committee,
            "activity_id": activity_id,
            "study_url":   full_url,
            "title":       title,
        })

    print(f"Found {len(studies)} active committee study/studies.\n")
    return studies


def get_brief_details(study: dict) -> dict | None:
    """
    Fetch a study activity page and look for call-for-briefs info.
    Returns a result dict, or None if the study has no open call for briefs.
    """
    soup = get_soup(study["study_url"])
    if soup is None:
        return None

    # The "Participate" section contains the deadline and submit button.
    # Look for any heading called "Participate" and grab the text beneath it.
    participate_text = ""
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if "participate" in heading.get_text(strip=True).lower():
            # Grab all sibling text until the next heading
            for sibling in heading.find_next_siblings():
                if sibling.name in ("h2", "h3", "h4"):
                    break
                participate_text += sibling.get_text(" ", strip=True) + " "
            break

    if not participate_text:
        # No "Participate" section found — likely no open call for briefs
        return None

    deadline_str, deadline_obj = parse_deadline(participate_text)

    # If the deadline has passed, skip it (stale)
    if deadline_obj and deadline_obj < date.today():
        return None

    # Build the submission link from the known pattern
    committee_lower = study["committee"].lower()
    submit_url = (
        f"{BASE_URL}/committee-participation/en/submit-brief/"
        f"{committee_lower}/{study['activity_id']}"
    )

    # Pull the full page title for a cleaner study name
    page_title = soup.find("h1")
    full_title = page_title.get_text(" ", strip=True) if page_title else study["title"]

    # Get the committee's full name from the <title> tag.
    # Page titles follow the pattern: "Study Name - Committee Name - ourcommons.ca"
    committee_name = study["committee"]   # fallback to acronym
    title_tag = soup.find("title")
    if title_tag:
        parts = [p.strip() for p in title_tag.get_text().split(" - ")]
        # The committee name is the second-to-last segment before "ourcommons.ca"
        for part in reversed(parts):
            if "committee" in part.lower() and len(part) < 100:
                committee_name = part
                break

    return {
        "source":       "House of Commons Committees",
        "title":        full_title,
        "committee":    committee_name,
        "summary":      participate_text.strip()[:400] + ("..." if len(participate_text) > 400 else ""),
        "deadline":     deadline_str,
        "url":          submit_url,
        "study_url":    study["study_url"],
    }


# ── Output ────────────────────────────────────────────────────────────────────

def print_results(briefs: list[dict]) -> None:
    if not briefs:
        print("\nNo open calls for briefs found at this time.")
        return

    print(f"\n{'=' * 72}")
    print(f"  HOUSE OF COMMONS -- OPEN CALLS FOR BRIEFS")
    print(f"  Retrieved: {date.today().strftime('%B %d, %Y')}")
    print(f"{'=' * 72}\n")

    for i, b in enumerate(briefs, start=1):
        print(f"[{i}] {b['title']}")
        print(f"    Committee  : {b['committee']}")
        print(f"    Deadline   : {b['deadline']}")
        print(f"    Details    : {b['summary']}")
        print(f"    Submit at  : {b['url']}")
        print(f"    Study page : {b['study_url']}")
        print(f"    {'-' * 68}\n")

    print(f"Total: {len(briefs)} open call(s) for briefs.")


# ── Public fetch function (called by generate_digest.py) ─────────────────────

def fetch() -> list[dict]:
    """Return all open calls for briefs. Used by the digest."""
    studies = get_study_links()
    briefs = []
    for study in studies:
        result = get_brief_details(study)
        if result:
            briefs.append(result)
    return briefs


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    studies = get_study_links()
    briefs = []
    for study in studies:
        print(f"Checking {study['committee']} — {study['title']} ...")
        result = get_brief_details(study)
        if result:
            briefs.append(result)
            print(f"  -> Open call found, deadline: {result['deadline']}")
        else:
            print(f"  -> No open call for briefs.")

    print_results(briefs)
