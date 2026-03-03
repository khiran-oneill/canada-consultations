"""
Canada Gazette Part I — Consultation Fetcher
=============================================
Checks recent issues of the Canada Gazette Part I for proposed regulations
that are open for public comment, and prints a plain-English summary of each.

Run it like this (after activating your virtual environment):
    python fetch_gazette.py
"""

import re
import sys
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta
from dateutil.parser import parse as parse_date

# ── Configuration ────────────────────────────────────────────────────────────

BASE_URL   = "https://gazette.gc.ca"
YEAR_INDEX = f"{BASE_URL}/rp-pr/p1/{date.today().year}/index-eng.html"

# Only look at issues published within the last N days.
# We use 60 so we catch items whose comment windows are still open.
LOOKBACK_DAYS = 60

# Polite browser headers — some servers refuse requests without a User-Agent.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; canada-consultations-bot/1.0; "
        "for personal research)"
    )
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_soup(url: str) -> BeautifulSoup | None:
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [warning] Could not fetch {url}: {e}", file=sys.stderr)
        return None


def extract_comment_deadline(text: str, pub_date: date) -> str:
    """
    The Canada Gazette states deadlines like:
      'Interested persons may make representations … within 30 days after …'
    We find that number and add it to the publication date.
    Returns a human-readable string, e.g. '2026-04-02 (30 days from pub date)'.
    """
    match = re.search(r"within\s+(\d+)\s+days?\s+after", text, re.IGNORECASE)
    if match:
        days = int(match.group(1))
        deadline = pub_date + timedelta(days=days)
        return f"{deadline.strftime('%B %d, %Y')}  ({days} days from publication)"
    return "Not specified — check the original notice"


def extract_summary(soup: BeautifulSoup) -> str:
    """
    Pull the first substantive paragraph(s) from a regulation page.
    The Gazette uses <section> or plain <p> tags for the body.
    We skip short boilerplate lines and grab the first real description.
    """
    paragraphs = []
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        # Skip short lines, navigation labels, and French content markers
        if len(text) < 80:
            continue
        # Skip the standard "representations within X days" boilerplate
        if re.search(r"representations.*days.*publication", text, re.IGNORECASE):
            continue
        paragraphs.append(text)
        if len(paragraphs) >= 2:          # two paragraphs is enough context
            break

    if paragraphs:
        combined = " ".join(paragraphs)
        # Trim to ~400 characters so the printout stays readable
        if len(combined) > 400:
            combined = combined[:397] + "..."
        return combined
    return "(No summary text found — please read the original notice.)"


# ── Main scraping logic ───────────────────────────────────────────────────────

def get_recent_issues() -> list[dict]:
    """
    Fetch the year-index page and return a list of issues published
    within the last LOOKBACK_DAYS days.
    Each item: { 'date': date, 'index_url': str }
    """
    print(f"Fetching year index: {YEAR_INDEX}")
    soup = get_soup(YEAR_INDEX)
    if soup is None:
        raise RuntimeError("Could not load the Canada Gazette year index. Check your internet connection.")

    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    issues = []

    # Every issue link contains a date-like path segment, e.g. /2026/2026-02-28/html/
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Match regular issue index pages (not extra editions for now)
        m = re.search(r"/p1/(\d{4})/(\d{4}-\d{2}-\d{2})/html/index-eng\.html", href)
        if not m:
            continue
        try:
            issue_date = datetime.strptime(m.group(2), "%Y-%m-%d").date()
        except ValueError:
            continue
        if issue_date < cutoff:
            continue

        full_url = BASE_URL + href if href.startswith("/") else href
        issues.append({"date": issue_date, "index_url": full_url})

    # Remove duplicates and sort newest-first
    seen = set()
    unique = []
    for issue in sorted(issues, key=lambda x: x["date"], reverse=True):
        if issue["index_url"] not in seen:
            seen.add(issue["index_url"])
            unique.append(issue)

    print(f"Found {len(unique)} issue(s) from the last {LOOKBACK_DAYS} days.\n")
    return unique


def get_proposed_regs(issue: dict) -> list[dict]:
    """
    Given an issue index page, find all links to proposed regulation pages
    (reg1-eng.html, reg2-eng.html, etc.) and return their details.
    Each item: { 'title', 'department', 'summary', 'deadline', 'url' }
    """
    soup = get_soup(issue["index_url"])
    if soup is None:
        return []

    # Proposed regulation pages follow the pattern reg1-eng.html, reg2-eng.html …
    # The href may appear as "reg1-eng.html" or "./reg1-eng.html"
    base = issue["index_url"].rsplit("/", 1)[0]   # strip "index-eng.html"
    reg_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].lstrip("./")             # normalise ./reg1-eng.html -> reg1-eng.html
        if re.match(r"reg\d+-eng\.html$", href):
            full_url = f"{base}/{href}"
            if full_url not in reg_links:
                reg_links.append(full_url)

    results = []
    for url in reg_links:
        print(f"  Reading regulation: {url}")
        reg_soup = get_soup(url)
        if reg_soup is None:
            continue

        # Title: the first <h1> or <h2> on the page
        title_tag = reg_soup.find("h1") or reg_soup.find("h2")
        title = title_tag.get_text(" ", strip=True) if title_tag else "Untitled"

        # Department: typically the second heading, or a line containing "Dept." / "Department"
        dept = "Unknown department"
        for tag in reg_soup.find_all(["h2", "h3", "p"]):
            t = tag.get_text(" ", strip=True)
            if re.search(r"(department|dept\.?|minister|commission|board|agency)",
                         t, re.IGNORECASE) and len(t) < 120:
                dept = t
                break

        full_text = reg_soup.get_text(" ", strip=True)
        deadline  = extract_comment_deadline(full_text, issue["date"])
        summary   = extract_summary(reg_soup)

        results.append({
            "title":      title,
            "department": dept,
            "summary":    summary,
            "deadline":   deadline,
            "pub_date":   issue["date"].strftime("%B %d, %Y"),
            "url":        url,
        })

    return results


# ── Output ────────────────────────────────────────────────────────────────────

def print_results(all_regs: list[dict]) -> None:
    if not all_regs:
        print("\nNo proposed regulations found in the lookback window.")
        return

    divider = "-" * 72
    print(f"\n{'=' * 72}")
    print(f"  CANADA GAZETTE -- PROPOSED REGULATIONS OPEN FOR COMMENT")
    print(f"  Showing items published in the last {LOOKBACK_DAYS} days")
    print(f"  Retrieved: {date.today().strftime('%B %d, %Y')}")
    print(f"{'=' * 72}\n")

    for i, reg in enumerate(all_regs, start=1):
        print(f"[{i}] {reg['title']}")
        print(f"    Department : {reg['department']}")
        print(f"    Published  : {reg['pub_date']}")
        print(f"    Deadline   : {reg['deadline']}")
        print(f"    Summary    : {reg['summary']}")
        print(f"    Link       : {reg['url']}")
        print(f"    {divider}\n")

    print(f"Total: {len(all_regs)} proposed regulation(s) found.")


# ── Public fetch function (called by generate_digest.py) ─────────────────────

def fetch() -> list[dict]:
    """Return all proposed regulations open for comment. Used by the digest."""
    issues = get_recent_issues()
    all_regs = []
    for issue in issues:
        regs = get_proposed_regs(issue)
        all_regs.extend(regs)
    return all_regs


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    issues  = get_recent_issues()
    all_regs = []
    for issue in issues:
        print(f"Scanning issue dated {issue['date']} ...")
        regs = get_proposed_regs(issue)
        all_regs.extend(regs)
        print(f"  -> {len(regs)} proposed regulation(s) found in this issue.")

    print_results(all_regs)
