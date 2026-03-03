"""
Ontario Legislature — Committee Notices of Hearings Fetcher
===========================================================
Checks the Legislative Assembly of Ontario's central notices page for any
committees currently accepting written submissions or holding public hearings.

There are 8 standing committees. When a committee holds a public hearing on a
bill or study, a notice appears on this page with the title, committee, and
deadline/hearing dates. Between sessions or when no hearings are scheduled,
the page simply says "There are currently no notices of hearings."

Run it like this (after activating your virtual environment):
    python fetch_ola.py
"""

import re
import sys
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL    = "https://www.ola.org"
NOTICES_URL = f"{BASE_URL}/en/legislative-business/committees/notices-hearings"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    )
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_soup(url: str) -> BeautifulSoup | None:
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [warning] Could not fetch {url}: {e}", file=sys.stderr)
        return None


def parse_deadline(text: str) -> tuple[str, date | None]:
    """
    Look for a date in text like 'Deadline: March 15, 2026' or
    'Written submissions accepted until April 30, 2026'.
    Returns (human_readable_label, date_object_or_None).
    """
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4}",
        text, re.IGNORECASE
    )
    if m:
        raw = m.group(0).replace(",", "")
        try:
            d = datetime.strptime(raw, "%B %d %Y").date()
            days_left = (d - date.today()).days
            if days_left < 0:
                suffix = f"(closed {abs(days_left)} days ago)"
            elif days_left == 0:
                suffix = "(closes TODAY)"
            else:
                suffix = f"({days_left} days remaining)"
            return f"{d.strftime('%B %d, %Y')}  {suffix}", d
        except ValueError:
            pass
    return "See hearing notice for deadline", None


# ── Main scraping logic ───────────────────────────────────────────────────────

def fetch_notices() -> list[dict]:
    """
    Fetch the central notices-of-hearings page and return active items.
    Returns an empty list if there are currently no hearings.

    Page structure (Drupal Views):
      <div class="view view-notice-of-hearings ...">
        <div class="view-empty">          <- shown when no hearings
          <p>There are currently no notices of hearings.</p>
        </div>
        -- OR --
        <div class="view-content">        <- shown when hearings exist
          <div class="views-row">...</div>
          ...
        </div>
      </div>
    """
    print(f"Fetching OLA committee notices of hearings ...")
    soup = get_soup(NOTICES_URL)
    if soup is None:
        raise RuntimeError("Could not load the OLA notices-of-hearings page.")

    # Find the Drupal Views block for notices
    view_div = soup.find(class_=re.compile(r"view-notice-of-hearings"))
    if not view_div:
        raise RuntimeError("Could not find the notices view on the OLA page.")

    # Empty state
    if view_div.find(class_="view-empty"):
        print("  No notices of hearings currently posted.")
        return []

    # Items state
    view_content = view_div.find(class_="view-content")
    if not view_content:
        print("  No view-content found — assuming no hearings.")
        return []

    results = []
    rows = view_content.find_all(class_=re.compile(r"views-row"))
    print(f"  Found {len(rows)} notice(s) of hearings.")

    for row in rows:
        # Title is typically an <h2>, <h3>, or <h4> containing a link
        title_tag = row.find(["h2", "h3", "h4"])
        if not title_tag:
            continue
        link = title_tag.find("a")
        title = (link or title_tag).get_text(" ", strip=True)
        href = ""
        if link and link.get("href"):
            href = link["href"]
            if not href.startswith("http"):
                href = BASE_URL + href

        # All text in the row for deadline extraction
        row_text = row.get_text(" ", strip=True)
        deadline_str, deadline_obj = parse_deadline(row_text)

        # Skip notices whose deadline has already passed
        if deadline_obj and deadline_obj < date.today():
            continue

        # Try to identify the committee from a secondary link or text block
        committee = ""
        for a in row.find_all("a"):
            t = a.get_text(strip=True)
            if t and t != title and "committee" in t.lower():
                committee = t
                break

        results.append({
            "source":    "Ontario Legislature — Committee Hearings",
            "title":     title,
            "committee": committee,
            "deadline":  deadline_str,
            "summary":   row_text[:400] if row_text else "",
            "url":       href or NOTICES_URL,
        })

    return results


# ── Output ────────────────────────────────────────────────────────────────────

def print_results(notices: list[dict]) -> None:
    if not notices:
        print("\nNo committee notices of hearings posted at this time.")
        return

    print(f"\n{'=' * 72}")
    print(f"  ONTARIO LEGISLATURE -- COMMITTEE NOTICES OF HEARINGS")
    print(f"  Retrieved: {date.today().strftime('%B %d, %Y')}")
    print(f"{'=' * 72}\n")

    for i, n in enumerate(notices, start=1):
        print(f"[{i}] {n['title']}")
        if n["committee"]:
            print(f"    Committee  : {n['committee']}")
        print(f"    Deadline   : {n['deadline']}")
        print(f"    Details    : {n['summary'][:200]}")
        print(f"    Notice URL : {n['url']}")
        print(f"    {'-' * 68}\n")

    print(f"Total: {len(notices)} active notice(s).")


# ── Public fetch function (called by generate_digest.py) ─────────────────────

def fetch() -> list[dict]:
    """Return all active committee hearing notices. Used by the digest."""
    return fetch_notices()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    notices = fetch_notices()
    print_results(notices)
