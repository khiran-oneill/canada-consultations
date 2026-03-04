"""
Department of Finance Canada — Consultations Fetcher
=====================================================
Scrapes the Finance Canada consultations page and visits each active
consultation to extract its deadline and a short description.

Run it standalone like this (after activating your virtual environment):
    python fetch_finance.py
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = "https://www.canada.ca"
MAIN_URL = f"{BASE_URL}/en/department-finance/programs/consultations.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; canada-consultations-bot/1.0; "
        "for personal research)"
    ),
}

# Date format used on Finance Canada pages
DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4}",
    re.IGNORECASE,
)

# Deadline signals (text that appears just before a closing date)
DEADLINE_SIGNALS = re.compile(
    r"(?:until|by|before|deadline[:\s]|closing date[:\s]|due\s+(?:date[:\s]|by\s))"
    r"\s*((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_deadline(text: str) -> date | None:
    """
    Extract the closing/deadline date from page body text.
    Looks for patterns like 'until April 13, 2026' or 'by March 13, 2026'.
    """
    m = DEADLINE_SIGNALS.search(text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%B %d, %Y").date()
        except ValueError:
            pass
    return None


def _get_summary(soup: BeautifulSoup) -> str:
    """Pull the first substantial paragraph from the main content."""
    main = soup.find("main") or soup.find(id="wb-main") or soup
    skip_phrases = {"date modified", "report a problem", "government of canada",
                    "share this page", "page details"}
    parts = []
    for p in main.find_all("p"):
        text = p.get_text(" ", strip=True)
        if len(text) < 60:
            continue
        if any(s in text.lower() for s in skip_phrases):
            continue
        parts.append(text)
        if len(parts) >= 2:
            break
    return " ".join(parts)[:500]


# ── Main scraping logic ───────────────────────────────────────────────────────

def _fetch_active_links(session: requests.Session) -> list[str]:
    """Return URLs for all active Finance consultations."""
    resp = session.get(MAIN_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    links = []
    # Find the heading that says "Active consultations" or similar
    for heading in soup.find_all(["h2", "h3"]):
        if "active" in heading.get_text(strip=True).lower():
            # Walk forward through siblings to find the <ul>
            node = heading.find_next_sibling()
            while node:
                if node.name == "ul":
                    for a in node.find_all("a", href=True):
                        href = a["href"]
                        if not href.startswith("http"):
                            href = BASE_URL + href
                        links.append(href)
                    break
                if node.name in ("h2", "h3"):
                    break
                node = node.find_next_sibling()
            break  # stop after the first "active" heading

    return links


def _fetch_detail(url: str, session: requests.Session) -> dict:
    """Visit a single consultation page and return title, deadline, summary."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    Warning: could not fetch {url}: {e}")
        return {}

    soup  = BeautifulSoup(resp.text, "html.parser")
    h1    = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""

    body_text = soup.get_text(" ", strip=True)
    deadline  = _find_deadline(body_text)
    summary   = _get_summary(soup)

    return {"title": title, "deadline": deadline, "summary": summary}


def fetch() -> list[dict]:
    """Fetch all active Department of Finance Canada consultations."""
    print("Fetching Department of Finance Canada consultations ...")
    today   = date.today()
    session = requests.Session()

    try:
        active_links = _fetch_active_links(session)
    except requests.RequestException as e:
        raise RuntimeError(f"Error fetching Finance consultations page: {e}")

    if not active_links:
        print("  No active consultation links found.")
        return []

    print(f"  Found {len(active_links)} active link(s). Visiting each ...")

    results = []
    for url in active_links:
        time.sleep(0.3)   # polite crawl delay
        detail = _fetch_detail(url, session)
        if not detail:
            continue

        title    = detail.get("title") or url.split("/")[-1].replace("-", " ").title()
        deadline = detail.get("deadline")

        # Skip if the deadline has already passed
        if deadline and deadline < today:
            continue

        if deadline:
            days_left    = (deadline - today).days
            deadline_str = f"{deadline.strftime('%B %d, %Y')} ({days_left} days remaining)"
        else:
            deadline_str = "Not specified"

        results.append({
            "source":     "Department of Finance Canada",
            "title":      title,
            "department": "Department of Finance Canada",
            "deadline":   deadline_str,
            "summary":    detail.get("summary", ""),
            "url":        url,
        })

    return results


# ── Standalone output ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    items = fetch()
    if not items:
        print("No active Finance Canada consultations found.")
    else:
        print(f"\nFound {len(items)} active consultation(s):\n")
        for i, item in enumerate(items, 1):
            print(f"[{i}] {item['title']}")
            print(f"    Deadline : {item['deadline']}")
            print(f"    URL      : {item['url']}")
            if item["summary"]:
                print(f"    Summary  : {item['summary'][:200]}...")
            print()
