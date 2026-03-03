"""
Ontario.ca — Consultations Directory Fetcher
============================================
Scrapes the Ontario government's consultations directory for any consultations
currently open or ongoing.

The page is static HTML with Open/Ongoing/Closed status badges.
"Ongoing" items have no fixed end date; "Open" items have a date range.
Previous/closed consultations are hidden in year-based accordion sections.

Run it like this (after activating your virtual environment):
    python fetch_ontario_ca.py
"""

import re
import sys
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = "https://www.ontario.ca"
DIR_URL  = f"{BASE_URL}/page/consultations-directory"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    )
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_end_date(date_text: str) -> date | None:
    """
    Extract the end date from a range like 'October 10, 2024 to February 6, 2025'.
    Returns a date object or None if no end date found.
    """
    m = re.search(
        r"to\s+(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        date_text or "", re.IGNORECASE
    )
    if m:
        try:
            return datetime.strptime(
                f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y"
            ).date()
        except ValueError:
            pass
    return None


def deadline_label(date_text: str, status: str) -> str:
    """Build a human-readable deadline string from the date range text."""
    if not date_text:
        return "No deadline listed (ongoing)" if status == "ongoing" else "No deadline listed"
    end = parse_end_date(date_text)
    if end is None:
        return date_text
    days_left = (end - date.today()).days
    if days_left < 0:
        return f"{date_text}  (closed {abs(days_left)} days ago)"
    elif days_left == 0:
        return f"{date_text}  (closes TODAY)"
    else:
        return f"{date_text}  ({days_left} days remaining)"


# ── Main scraping logic ───────────────────────────────────────────────────────

def fetch_consultations() -> list[dict]:
    """
    Fetch open and ongoing items from the Ontario.ca consultations directory.

    Page structure:
      <h3>Title of consultation</h3>
      <div>
        <span class="show-for-sr">Status</span>
        <span class="badge open">Open</span>     <- or "ongoing"
        <span> October 10, 2024 to February 6, 2025</span>  <- date range (Open only)
      </div>
      <p>Description paragraph.</p>
      <p><span class="small">Ministry Name</span></p>
      <p><a class="button" href="/page/...">Participate</a></p>
      <hr>
      ...
      <h2>Previous consultations</h2>  <- stop here
    """
    print("Fetching Ontario.ca consultations directory ...")
    try:
        r = requests.get(DIR_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Could not load Ontario.ca consultations directory: {e}")

    soup = BeautifulSoup(r.text, "html.parser")

    # Find the 'Previous consultations' h2 so we stop before reaching it
    prev_marker = None
    for tag in soup.find_all("h2"):
        if "previous" in tag.get_text(strip=True).lower():
            prev_marker = tag
            break

    results = []

    for h3 in soup.find_all("h3"):
        # Stop once we've passed the current-consultations section
        if prev_marker:
            # h3.find_previous("h2") gives the closest h2 before this h3
            nearest_h2 = h3.find_previous("h2")
            if nearest_h2 == prev_marker:
                break

        # The badge lives in the immediately following <div>
        badge_div = h3.find_next_sibling("div")
        if not badge_div:
            continue
        badge = badge_div.find("span", class_="badge")
        if not badge:
            continue

        status = badge.get_text(strip=True).lower()
        if status not in ("open", "ongoing"):
            continue

        title = h3.get_text(" ", strip=True)

        # Date range: the span after the badge (no 'badge' or 'show-for-sr' class)
        date_text = ""
        for span in badge_div.find_all("span"):
            classes = span.get("class", [])
            if "badge" not in classes and "show-for-sr" not in classes:
                date_text = span.get_text(strip=True)
                break

        # Skip "open" items whose end date has already passed
        if status == "open" and date_text:
            end = parse_end_date(date_text)
            if end and end < date.today():
                continue

        # Walk following siblings for description, ministry, and link
        desc = ""
        ministry = ""
        link = ""
        for sib in h3.find_next_siblings(["p", "div", "h2", "h3", "hr"]):
            if sib.name in ("h2", "h3", "hr"):
                break
            if sib.name == "div":
                if sib == badge_div:
                    continue
                # Could be another wrapper; skip
                continue
            # It's a <p>
            small = sib.find(class_="small")
            if small:
                ministry = small.get_text(strip=True)
                continue
            btn = sib.find("a", class_="button")
            if btn:
                href = btn.get("href", "")
                link = href if href.startswith("http") else BASE_URL + href
                continue
            # Plain description paragraph
            if not desc:
                desc = sib.get_text(" ", strip=True)

        results.append({
            "source":     "Ontario.ca — Consultations",
            "title":      title,
            "department": ministry,
            "summary":    desc[:400] if desc else "(See consultation page for details.)",
            "deadline":   deadline_label(date_text, status),
            "status":     status.capitalize(),
            "url":        link or DIR_URL,
        })

    print(f"  Found {len(results)} open/ongoing consultation(s).")
    return results


# ── Output ────────────────────────────────────────────────────────────────────

def print_results(consultations: list[dict]) -> None:
    if not consultations:
        print("\nNo open consultations on Ontario.ca at this time.")
        return

    print(f"\n{'=' * 72}")
    print(f"  ONTARIO.CA -- CONSULTATIONS DIRECTORY")
    print(f"  Retrieved: {date.today().strftime('%B %d, %Y')}")
    print(f"{'=' * 72}\n")

    for i, c in enumerate(consultations, start=1):
        print(f"[{i}] {c['title']}")
        print(f"    Ministry   : {c['department']}")
        print(f"    Status     : {c['status']}")
        print(f"    Deadline   : {c['deadline']}")
        print(f"    Summary    : {c['summary'][:200]}")
        print(f"    Link       : {c['url']}")
        print(f"    {'-' * 68}\n")

    print(f"Total: {len(consultations)} open/ongoing consultation(s).")


# ── Public fetch function (called by generate_digest.py) ─────────────────────

def fetch() -> list[dict]:
    """Return all open/ongoing consultations. Used by the digest."""
    return fetch_consultations()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    consultations = fetch_consultations()
    print_results(consultations)
