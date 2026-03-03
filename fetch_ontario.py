"""
Ontario Regulatory Registry — Open Proposals Fetcher
=====================================================
Queries the Ontario Regulatory Registry's internal API (discovered through
JS analysis) to find all proposals currently open for public comment.

The API is public-facing (no login required); it uses a public API key
that is loaded from the site's own config endpoint on each page visit.

Run it like this (after activating your virtual environment):
    python fetch_ontario.py
"""

import re
import sys
import requests
from datetime import date, datetime

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL   = "https://www.regulatoryregistry.gov.on.ca"
CONFIG_URL = f"{BASE_URL}/api/api/config"       # returns the public API key
POSTS_URL  = f"{BASE_URL}/api/api/postings/specification"
MINIST_URL = f"{BASE_URL}/api/api/ministries"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; canada-consultations-bot/1.0; "
        "for personal research)"
    ),
    "Accept": "application/json",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_api_key() -> str:
    """
    Fetch the public config endpoint to get the current API key.
    The key is embedded in the site's own config and is not secret —
    it's loaded and stored in the browser's localStorage on every visit.
    """
    try:
        r = requests.get(CONFIG_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json().get("apiKey", "")
    except Exception as e:
        raise RuntimeError(f"Could not load Ontario Registry config: {e}")


def get_ministries(api_key: str) -> dict[int, str]:
    """Return a dict mapping ministryId -> ministryName."""
    hdrs = {**HEADERS, "x-api-key": api_key}
    try:
        r = requests.get(MINIST_URL, headers=hdrs, timeout=15)
        r.raise_for_status()
        return {m["ministryId"]: m["ministryName"] for m in r.json()}
    except Exception:
        return {}   # non-fatal; we'll fall back to the ministry ID


def strip_html(text: str) -> str:
    """Remove HTML tags and normalise whitespace."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def trim(text: str, max_chars: int = 400) -> str:
    text = text.strip()
    if len(text) > max_chars:
        return text[:max_chars - 3] + "..."
    return text


def deadline_label(due_str: str) -> str:
    """
    The API returns dates like 'Apr 05, 2026'.
    Return a human-readable label with days remaining.
    """
    if not due_str:
        return "No deadline listed"
    try:
        due = datetime.strptime(due_str, "%b %d, %Y").date()
        days_left = (due - date.today()).days
        if days_left < 0:
            return f"{due_str}  (closed {abs(days_left)} days ago)"
        elif days_left == 0:
            return f"{due_str}  (closes TODAY)"
        else:
            return f"{due_str}  ({days_left} days remaining)"
    except ValueError:
        return due_str


# ── Main scraping logic ───────────────────────────────────────────────────────

def fetch_proposals() -> list[dict]:
    """
    Fetch all proposals currently open for public comment from the Registry.
    Returns a list of normalised dicts.
    """
    print("Fetching public API key from Ontario Regulatory Registry ...")
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("Could not obtain API key from Registry config.")

    hdrs = {**HEADERS, "x-api-key": api_key}

    print("Loading ministry names ...")
    ministries = get_ministries(api_key)

    print("Fetching open proposals ...")
    params = {
        "postingStatusIds":               3,         # 3 = published/open
        "commentsDueDateIsAfterInclusive": date.today().isoformat(),
        "orderBy":                        "commentsDueDate",
        "orderDirection":                 "asc",     # soonest deadline first
        "page":                           0,
        "size":                           200,       # fetch all (typically < 50 open)
    }
    try:
        r = requests.get(POSTS_URL, headers=hdrs, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"Error fetching proposals: {e}")

    items = data.get("content", [])
    print(f"Found {len(items)} open proposal(s).\n")

    results = []
    for item in items:
        posting_id = item.get("postingId", "")
        tracking   = item.get("trackingNumber", "")
        ministry_id = item.get("ministryId")
        ministry   = ministries.get(ministry_id, f"Ministry #{ministry_id}")
        title      = item.get("title") or item.get("titleFr") or "Untitled"
        due_str    = item.get("commentsDueDate", "")
        summary    = strip_html(item.get("summary") or item.get("description") or "")

        # The proposal page URL on the registry site
        proposal_url = f"{BASE_URL}/proposal/{posting_id}"

        # Some postings also appear on an external host (e.g. ERO)
        host_url = item.get("hostUrl") or item.get("hostUrlFr") or ""

        results.append({
            "source":      "Ontario Regulatory Registry",
            "title":       title,
            "department":  ministry,
            "tracking":    tracking,
            "summary":     trim(summary) if summary else "(See original proposal for details.)",
            "deadline":    deadline_label(due_str),
            "url":         proposal_url,
            "external_url": host_url,
        })

    return results


# ── Output ────────────────────────────────────────────────────────────────────

def print_results(proposals: list[dict]) -> None:
    if not proposals:
        print("No open proposals found at this time.")
        return

    print(f"{'=' * 72}")
    print(f"  ONTARIO REGULATORY REGISTRY -- OPEN FOR COMMENT")
    print(f"  Retrieved: {date.today().strftime('%B %d, %Y')}")
    print(f"{'=' * 72}\n")

    for i, p in enumerate(proposals, start=1):
        print(f"[{i}] {p['title']}")
        print(f"    Ministry     : {p['department']}")
        print(f"    Tracking #   : {p['tracking']}")
        print(f"    Deadline     : {p['deadline']}")
        print(f"    Summary      : {p['summary']}")
        print(f"    Registry URL : {p['url']}")
        if p["external_url"]:
            print(f"    Also at      : {p['external_url']}")
        print(f"    {'-' * 68}\n")

    print(f"Total: {len(proposals)} open proposal(s).")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    proposals = fetch_proposals()
    print_results(proposals)
