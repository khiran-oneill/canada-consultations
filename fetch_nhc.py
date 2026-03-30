"""
National Housing Council — Review Panel Written Hearings Fetcher
================================================================
Scrapes the NHC "Current Review Panels" page to find active panels,
then visits each panel's detail page to extract the written hearing
deadline.

Sources:
  - https://nhc-cnl.ca/review-panels/current  (listing of active panels)
  - Each panel's detail page (e.g. /review-panels/review-5)

Note: nhc-cnl.ca presents SSL certificate errors on some systems.
The scraper retries without SSL verification if the first attempt fails.

Run it like this (after activating your virtual environment):
    python fetch_nhc.py
"""

import re
import sys
import requests
import urllib3
from bs4 import BeautifulSoup
from datetime import date, datetime

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL    = "https://nhc-cnl.ca"
CURRENT_URL = f"{BASE_URL}/review-panels/current"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; canada-consultations-bot/1.0; "
        "for personal research)"
    ),
}

# Pattern: "Submissions will be accepted until June 5, 2026"
# or "deadline is April 30, 2026", "by June 5, 2026", etc.
_DEADLINE_RE = re.compile(
    r"(?:accepted\s+until|deadline(?:\s+is)?|by|before|closes?\s*(?:on)?|until|no\s+later\s+than)"
    r"\s*[:\-]?\s*"
    r"((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(url: str) -> BeautifulSoup | None:
    """Fetch a URL (with SSL retry) and return a BeautifulSoup object."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    for verify in (True, False):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20, verify=verify)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.exceptions.SSLError:
            if verify:
                continue
            print(f"  [warning] SSL error — could not fetch {url}", file=sys.stderr)
            return None
        except requests.RequestException as e:
            print(f"  [warning] Could not fetch {url}: {e}", file=sys.stderr)
            return None
    return None


def _parse_deadline(text: str) -> tuple[date | None, str]:
    """
    Extract a deadline date from body text.
    Returns (date object or None, human-readable deadline string).
    """
    m = _DEADLINE_RE.search(text)
    if m:
        try:
            d = datetime.strptime(m.group(1), "%B %d, %Y").date()
            days_left = (d - date.today()).days
            if days_left < 0:
                return None, f"{d.strftime('%B %d, %Y')} (closed)"
            elif days_left == 0:
                return d, f"{d.strftime('%B %d, %Y')} (closes TODAY)"
            else:
                return d, f"{d.strftime('%B %d, %Y')} ({days_left} days remaining)"
        except ValueError:
            pass
    return None, "Not specified — check the NHC website"


# ── Main scraping logic ───────────────────────────────────────────────────────

def _get_panel_cards(soup: BeautifulSoup) -> list[dict]:
    """
    Parse the /review-panels/current page and return a list of
    { title, url, start_date } for each active panel card.

    Each card has this structure:
        <div class="p-8 bg-white border border-accent-dark/50 ...">
          <h3 class="h4">Panel Title</h3>
          <div class="font-light text-base">YYYY-MM-DD</div>
          <a href="https://nhc-cnl.ca/review-panels/review-N">Learn More</a>
        </div>
    """
    cards = []
    for div in soup.find_all("div", class_=lambda c: c and "bg-white" in c and "border" in c):
        h3 = div.find("h3")
        if not h3:
            continue
        title = h3.get_text(" ", strip=True).strip()
        if not title or len(title) < 10:
            continue

        a_tag = div.find("a", href=True)
        url   = a_tag["href"] if a_tag else CURRENT_URL
        if url.startswith("/"):
            url = BASE_URL + url

        # Start date — "font-light" div
        start_date = ""
        date_div = div.find("div", class_=lambda c: c and "font-light" in c)
        if date_div:
            start_date = date_div.get_text(strip=True)

        cards.append({"title": title, "url": url, "start_date": start_date})
    return cards


def _get_panel_detail(url: str) -> dict:
    """
    Visit a panel detail page and extract its summary and written hearing deadline.
    Returns { summary, deadline_obj, deadline_str }.
    """
    soup = _get(url)
    if soup is None:
        return {"summary": "", "deadline_obj": None, "deadline_str": "Not specified — check the NHC website"}

    body_text = soup.get_text(" ", strip=True)
    deadline_obj, deadline_str = _parse_deadline(body_text)

    # Get a meaningful summary paragraph (skip nav/boilerplate)
    summary = ""
    nav_skip = {"home", "about us", "contact", "sign-up", "disclaimer", "navigation"}
    main = soup.find("main") or soup.body
    if main:
        for p in main.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) < 80:
                continue
            if any(s in t.lower() for s in nav_skip):
                continue
            summary = t[:400]
            break

    return {"summary": summary, "deadline_obj": deadline_obj, "deadline_str": deadline_str}


# ── Public fetch function ─────────────────────────────────────────────────────

def fetch() -> list[dict]:
    """
    Fetch all active NHC review panel written hearing opportunities.
    Returns a list of item dicts compatible with generate_digest.py.
    """
    print("Fetching National Housing Council review panel hearings ...")
    today = date.today()

    soup = _get(CURRENT_URL)
    if soup is None:
        raise RuntimeError("Could not fetch NHC current review panels page.")

    cards = _get_panel_cards(soup)
    if not cards:
        print("  No panel cards found on the current panels page.")
        return []

    results = []
    for card in cards:
        detail = _get_panel_detail(card["url"])

        # Skip if deadline has already passed
        if detail["deadline_obj"] is not None and detail["deadline_obj"] < today:
            continue

        results.append({
            "source":     "National Housing Council — Review Panel Hearings",
            "title":      card["title"],
            "department": "National Housing Council (NHC)",
            "summary":    detail["summary"],
            "deadline":   detail["deadline_str"],
            "url":        card["url"],
        })

    print(f"  Found {len(results)} active NHC review panel hearing(s).")
    return results


# ── Standalone output ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    items = fetch()
    if not items:
        print("No active NHC review panel hearings found.")
    else:
        print(f"\nFound {len(items)} active hearing(s):\n")
        for i, item in enumerate(items, 1):
            print(f"[{i}] {item['title']}")
            print(f"    Deadline : {item['deadline']}")
            print(f"    URL      : {item['url']}")
            if item["summary"]:
                print(f"    Summary  : {item['summary'][:200]}")
            print()
