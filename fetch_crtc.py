"""
CRTC — Open Consultations Fetcher
===================================
Scrapes the CRTC's "Have your say" consultations page and returns all
consultations that are currently open for public comment.

Each consultation card on the page follows this structure:
    <a href="/eng/consultation/foo.htm">
      <h3>Title</h3>
      <img ...>
      <p>Brief description</p>
      <strong>Status: open from March 18 to September 18, 2026</strong>
    </a>

Run it like this (after activating your virtual environment):
    python fetch_crtc.py
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime

# ── Configuration ─────────────────────────────────────────────────────────────

CONSULTATIONS_URL = "https://web.crtc.gc.ca/eng/consultation/"
CRTC_BASE         = "https://www.crtc.gc.ca"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; canada-consultations-bot/1.0; "
        "for personal research)"
    ),
}

# Matches the closing date in status strings like:
#   "Status: open from March 18 to September 18, 2026"
_OPEN_TO_RE = re.compile(
    r"\bto\s+((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_deadline(status_text: str) -> tuple[date | None, str]:
    """
    Extract the closing date from status text like:
      'Status: open from March 18 to September 18, 2026'
    Returns (date object or None, human-readable deadline string).
    """
    m = _OPEN_TO_RE.search(status_text)
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
    return None, "Not specified — check the CRTC website"


# ── Main scraping logic ───────────────────────────────────────────────────────

def fetch() -> list[dict]:
    """
    Fetch all CRTC consultations that are currently open for comment.
    Returns a list of item dicts compatible with generate_digest.py.
    """
    print("Fetching CRTC open consultations ...")
    today = date.today()

    try:
        resp = requests.get(CONSULTATIONS_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Error fetching CRTC consultations page: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")

    results   = []
    seen_urls = set()

    # Actual page structure (from the "Featured consultations" section):
    #
    #   <div class="col-lg-4 col-md-6 mrgn-bttm-md">
    #     <a href="/eng/consultation/indg-atch.htm">
    #       <figure>
    #         <figcaption>Title text<span ...></span></figcaption>
    #         <img .../>
    #       </figure>
    #     </a>
    #     <p>Description text</p>
    #     <p class="small"><strong>Status: open from March 18 to September 18, 2026</strong></p>
    #   </div>
    #
    # The title is in <figcaption> and the status is a sibling <p>, NOT inside the <a>.

    for card in soup.find_all("div", class_=lambda c: c and "col-lg-4" in c and "col-md-6" in c):
        a_tag = card.find("a", href=True)
        if not a_tag:
            continue

        href = a_tag.get("href", "")
        if not re.search(r"/eng/consultation/[\w-]+\.htm", href):
            continue

        # Build absolute URL
        if href.startswith("/"):
            url = CRTC_BASE + href
        elif href.startswith("http"):
            url = href
        else:
            continue

        if url in seen_urls:
            continue

        # Title is in <figcaption> inside the <a>
        figcaption = a_tag.find("figcaption")
        if not figcaption:
            continue
        # Strip any nested <span> tags that contain just whitespace/breaks
        for span in figcaption.find_all("span"):
            span.decompose()
        title = figcaption.get_text(" ", strip=True)
        if not title:
            continue

        # Status text is in <p class="small"><strong>Status: ...</strong></p>
        # It is a sibling of the <a>, not inside it
        status_text = ""
        for p in card.find_all("p"):
            strong = p.find("strong")
            if strong and "Status" in strong.get_text():
                status_text = strong.get_text(" ", strip=True)
                break

        # Skip consultations not currently open
        if re.search(r"closed\s+for\s+comments|decision\s+issued", status_text, re.IGNORECASE):
            continue

        deadline_obj, deadline_str = _parse_deadline(status_text)

        # Skip if deadline has already passed
        if deadline_obj is not None and deadline_obj < today:
            continue

        # Description is the non-small <p> sibling
        summary = ""
        for p in card.find_all("p"):
            if "small" not in (p.get("class") or []):
                t = p.get_text(" ", strip=True)
                if len(t) > 20:
                    summary = t[:400]
                    break

        seen_urls.add(url)
        results.append({
            "source":     "CRTC — Consultations",
            "title":      title,
            "department": "Canadian Radio-television and Telecommunications Commission (CRTC)",
            "summary":    summary,
            "deadline":   deadline_str,
            "url":        url,
        })

    print(f"  Found {len(results)} open CRTC consultation(s).")
    return results


# ── Standalone output ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    items = fetch()
    if not items:
        print("No open CRTC consultations found.")
    else:
        print(f"\nFound {len(items)} open consultation(s):\n")
        for i, item in enumerate(items, 1):
            print(f"[{i}] {item['title']}")
            print(f"    Deadline : {item['deadline']}")
            print(f"    URL      : {item['url']}")
            if item["summary"]:
                print(f"    Summary  : {item['summary'][:200]}")
            print()
