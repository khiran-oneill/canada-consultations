"""
Canadian Consultations — Daily Digest Generator
================================================
Runs all seven scrapers, combines the results, and produces a clean
HTML file you can open in any browser.

Run it like this (after activating your virtual environment):
    python generate_digest.py

The output file is saved as:  digest_YYYY-MM-DD.html
"""

import sys
import re
import json
from datetime import date, datetime, timedelta
from jinja2 import Environment, BaseLoader

# ── Import all eight scrapers ─────────────────────────────────────────────────
import fetch_gazette
import fetch_canada_ca
import fetch_hoc
import fetch_senate
import fetch_ontario
import fetch_ontario_ca
import fetch_ola
import fetch_finance

# ── Content filter ───────────────────────────────────────────────────────────
#
# Consultations whose title contains any of these phrases (case-insensitive)
# are hidden from the main digest and shown only as a collapsed count.
# Add or remove phrases here to tune what gets filtered out.

BLOCKLIST = [
    # ── Species at risk ───────────────────────────────────────────────────────
    "recovery strategy",              # Recovery Strategy for the Wolverine...
    "management plan for",            # Management Plan for the Grizzly Bear...
    "action plan for the",            # Action Plan for the Woodland Caribou...
    "critical habitat for",           # Critical Habitat Order for the...
    "proposed listing",               # Species listing decisions under SARA
    "cosewic",                        # Committee on the Status of Endangered Wildlife
    "national wildlife area",         # Specific wildlife area designations
    "migratory bird sanctuary",       # Specific sanctuary designations

    # ── Food & agriculture technical ──────────────────────────────────────────
    "feed ingredient",                # Proposed amended livestock feed ingredient
    "livestock feed",                 # Livestock Feed Regulations
    "food additive",                  # Technical food additive approvals
    "novel food",                     # New food substance approvals
    "vitamin",                        # Vitamin E acetate, etc.
    "mineral supplement",             # Specific supplement regulations
    "crop protection",                # Pesticide/product approvals
    "variety registration",           # Seed variety technical registrations
    "plant variety",                  # Plant Variety Protection

    # ── Fisheries & wildlife technical ───────────────────────────────────────
    "total allowable catch",          # Annual quota-setting notices
    "integrated fisheries management",# Very specific fisheries management plans

    # ── Pest control & residue limits ─────────────────────────────────────────
    "pest control product",           # Pesticide registrations
    "maximum residue limit",          # Pesticide residue in food
    "residue limit",                  # Residue limits (shorter form)

    # ── Drug & health product technical ──────────────────────────────────────
    "veterinary drug",                # Specific veterinary drug approvals
    "natural health product",         # Supplement/NHP technical approvals
    "drug submission",                # Pharmaceutical technical submissions

    # ── Chemical & substance registration (CEPA) ──────────────────────────────
    "new substance notification",     # Chemical notification requirements
    "significant new activity",       # CEPA s.85/106 notices

    # ── Environmental technical ───────────────────────────────────────────────
    "effluent",                       # Specific discharge concentration limits
    "ambient air quality",            # Technical air quality monitoring standards
    "wastewater system",              # Specific wastewater technical rules

    # ── Nuclear & radiation ───────────────────────────────────────────────────
    "nuclear substance",              # Nuclear substance regulations
    "radioactive",                    # Radioactive waste, nuclear technical items

    # ── Transport technical ───────────────────────────────────────────────────
    "airworthiness",                  # Aviation airworthiness directives
    "load line",                      # Marine load line technical standards

    # ── Broadcasting & telecom technical ──────────────────────────────────────
    "radio apparatus",                # Equipment technical standards

    # ── Transport technical ───────────────────────────────────────────────────
    "dangerous goods",                # Transport of Dangerous Goods exemptions
    "airspace",                       # Aviation airspace technical designations
    "vessel construction",            # Marine vessel technical standards

    # ── More agriculture ──────────────────────────────────────────────────────
    "fertilizer",                     # Specific fertilizer composition rules
    "grain grading",                  # Grain inspection and grading technical
    "seed potato",                    # Agricultural seed certification

    # ── More pharmaceutical / health products ─────────────────────────────────
    "biologic",                       # Biologic drug technical approvals
    "therapeutic product",            # Health product technical submissions
    "occupational exposure limit",    # Workplace chemical exposure thresholds

    # ── Environmental disposal & waste ────────────────────────────────────────
    "disposal at sea",                # Marine disposal permit applications
    "sewage system",                  # Small sewage system technical rules

    # ── Gazette housekeeping ──────────────────────────────────────────────────
    "miscellaneous amendments",       # Regulatory housekeeping notices
    "corrections and errata",         # Gazette corrections, never substantive

    # ── Other narrow technical ────────────────────────────────────────────────
    "calibration",                    # Laboratory/measurement standards
    "tariff item",                    # Customs tariff technical amendments
]


# ── "New today" tracking ──────────────────────────────────────────────────────

PREVIOUS_ITEMS_FILE = "previous_items.json"

def load_previous_keys() -> set:
    """Load item keys from the last run, or empty set if first run."""
    try:
        with open(PREVIOUS_ITEMS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f).get("keys", []))
    except (FileNotFoundError, ValueError):
        return set()

def save_current_keys(keys: list) -> None:
    """Persist current item keys so tomorrow's run can detect new arrivals."""
    with open(PREVIOUS_ITEMS_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": date.today().isoformat(), "keys": sorted(keys)}, f, indent=2)


def is_filtered(item: dict) -> bool:
    """Return True if this item's title matches a blocklist phrase."""
    title = item.get("title", "").lower()
    return any(phrase in title for phrase in BLOCKLIST)


# ── Urgency helpers ───────────────────────────────────────────────────────────

def _extract_date(deadline_str: str) -> date | None:
    """Pull a date out of a deadline string like 'March 30, 2026  (27 days remaining)'."""
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},\s+\d{4}",
        deadline_str or "", re.IGNORECASE
    )
    if m:
        try:
            return datetime.strptime(m.group(0), "%B %d, %Y").date()
        except ValueError:
            pass
    return None


def urgency(item: dict) -> str:
    """
    Return a CSS class name based on how soon the deadline is.
      'urgent'  — closes within 7 days
      'soon'    — closes within 30 days
      'open'    — closes in 30+ days or no deadline
      'ongoing' — Senate studies (no fixed deadline)
    """
    # Senate studies have no comment deadline
    if item.get("source") == "Senate of Canada Committees":
        return "ongoing"

    deadline_str = item.get("deadline", "")
    d = _extract_date(deadline_str)
    if d is None:
        return "open"
    days_left = (d - date.today()).days
    if days_left <= 7:
        return "urgent"
    elif days_left <= 30:
        return "soon"
    return "open"


# ── Collect data from all scrapers ────────────────────────────────────────────

def collect_all() -> dict:
    """
    Run all five scrapers and return a dict of sections.
    Each section has a list of items and a metadata label.
    """
    sections = []
    total = 0
    previous_keys = load_previous_keys()
    current_keys  = []

    senate_cutoff = (date.today() - timedelta(days=30)).strftime("%B %d, %Y")

    sources = [
        {
            "id":       "hoc",
            "label":    "House of Commons — Open Calls for Briefs",
            "icon":     "HC",
            "color":    "#8B0000",
            "fetch":    fetch_hoc.fetch,
            "note":     "Deadline shown is the brief submission deadline.",
        },
        {
            "id":       "gazette",
            "label":    "Canada Gazette Part I — Proposed Regulations",
            "icon":     "CG",
            "color":    "#C8102E",
            "fetch":    lambda: fetch_gazette.fetch(),
            "note":     "Comment period opens from the publication date.",
        },
        {
            "id":       "canada_ca",
            "label":    "Canada.ca — Federal Consultations",
            "icon":     "FED",
            "color":    "#26374A",
            "fetch":    fetch_canada_ca.fetch_consultations,
            "note":     "Showing open consultations with future deadlines, sorted soonest first.",
        },
        {
            "id":       "ontario",
            "label":    "Ontario Regulatory Registry — Open Proposals",
            "icon":     "ON",
            "color":    "#00698F",
            "fetch":    fetch_ontario.fetch_proposals,
            "note":     "All proposals currently accepting public comment.",
        },
        {
            "id":       "ontario_ca",
            "label":    "Ontario.ca — Consultations Directory",
            "icon":     "ONT",
            "color":    "#1A6496",
            "fetch":    fetch_ontario_ca.fetch,
            "note":     "Open and ongoing public consultations posted by the Ontario government.",
        },
        {
            "id":       "ola",
            "label":    "Ontario Legislature — Committee Hearings",
            "icon":     "OLA",
            "color":    "#5C3A1E",
            "fetch":    fetch_ola.fetch,
            "note":     (
                "Active notices of public hearings by Ontario standing committees. "
                "When a committee is studying a bill or issue, it posts a notice here "
                "with hearing dates and a submission deadline."
            ),
        },
        {
            "id":       "senate",
            "label":    "Senate of Canada — Active Committee Studies",
            "icon":     "SEN",
            "color":    "#6B3A8B",
            "fetch":    fetch_senate.fetch_studies,
            "note":     (
                f"Showing only Senate committee studies referred since {senate_cutoff} (last 30 days). "
                f"Studies referred before that date are not shown here, but may still be active. "
                f"Senate committees accept written briefs at any time during a study — no fixed deadline. "
                f"To submit, email ctm@sen.parl.gc.ca with the study title and committee name."
            ),
        },
        {
            "id":       "finance",
            "label":    "Department of Finance Canada — Consultations",
            "icon":     "FIN",
            "color":    "#1D4E2B",
            "fetch":    fetch_finance.fetch,
            "note":     "Active public consultations from the Department of Finance Canada.",
        },
    ]

    for src in sources:
        print(f"  Fetching: {src['label']} ...")
        try:
            items = src["fetch"]()
        except (Exception, SystemExit) as e:
            print(f"    [warning] Failed — skipping this source: {e}", file=sys.stderr)
            items = []

        # Split into shown and filtered, tag shown items with urgency
        shown = []
        filtered_titles = []
        for item in items:
            if is_filtered(item):
                filtered_titles.append(item.get("title", ""))
            else:
                item["_urgency"] = urgency(item)
                key = f"{item.get('source', '')}|{item.get('title', '')}"
                item["_key"]    = key
                item["_is_new"] = key not in previous_keys
                current_keys.append(key)
                shown.append(item)

        sections.append({
            "id":              src["id"],
            "label":           src["label"],
            "icon":            src["icon"],
            "color":           src["color"],
            "note":            src["note"],
            "entries":         shown,
            "count":           len(shown),
            "filtered_count":  len(filtered_titles),
            "filtered_titles": filtered_titles,
        })
        total += len(shown)
        filtered_note = f", {len(filtered_titles)} filtered" if filtered_titles else ""
        print(f"    -> {len(shown)} item(s){filtered_note}")

    save_current_keys(current_keys)
    new_count    = sum(1 for s in sections for i in s["entries"] if i.get("_is_new"))
    urgent_count = sum(1 for s in sections for i in s["entries"] if i.get("_urgency") == "urgent")
    return {
        "sections":     sections,
        "total":        total,
        "today":        date.today(),
        "new_count":    new_count,
        "urgent_count": urgent_count,
    }


# ── Jinja2 HTML template ──────────────────────────────────────────────────────

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Canadian Consultations Digest — {{ today.strftime('%B %d, %Y') }}</title>
  <style>
    /* ── Reset & base ── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                   "Helvetica Neue", Arial, sans-serif;
      font-size: 15px;
      line-height: 1.6;
      background: #f4f5f7;
      color: #1a1a1a;
    }

    /* ── Page header ── */
    .page-header {
      background: #26374A;
      color: #fff;
      padding: 2rem 2.5rem 1.5rem;
    }
    .page-header h1 { font-size: 1.6rem; font-weight: 700; margin-bottom: 0.25rem; }
    .page-header .subtitle { font-size: 0.9rem; opacity: 0.8; }
    .page-header .total-badge {
      display: inline-block;
      background: #fff;
      color: #26374A;
      font-weight: 700;
      font-size: 0.85rem;
      padding: 0.2rem 0.75rem;
      border-radius: 20px;
      margin-top: 0.75rem;
    }

    /* ── Table of contents ── */
    .toc {
      background: #fff;
      border-bottom: 1px solid #ddd;
      padding: 0.75rem 2.5rem;
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }
    .toc a {
      font-size: 0.82rem;
      color: #26374A;
      text-decoration: none;
      border: 1px solid #ccc;
      border-radius: 4px;
      padding: 0.2rem 0.6rem;
      white-space: nowrap;
    }
    .toc a:hover { background: #f0f0f0; }

    /* ── Main layout ── */
    .content { max-width: 960px; margin: 2rem auto; padding: 0 1.5rem; }

    /* ── Section ── */
    .section { margin-bottom: 3rem; }
    .section-header {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 1rem;
      padding-bottom: 0.5rem;
      border-bottom: 3px solid var(--section-color);
    }
    .section-icon {
      background: var(--section-color);
      color: #fff;
      font-size: 0.72rem;
      font-weight: 800;
      letter-spacing: 0.04em;
      padding: 0.3rem 0.5rem;
      border-radius: 4px;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .section-header h2 { font-size: 1.1rem; color: var(--section-color); }
    .section-count {
      margin-left: auto;
      font-size: 0.82rem;
      color: #555;
      flex-shrink: 0;
    }
    .section-note {
      font-size: 0.82rem;
      color: #555;
      background: #f8f8f8;
      border-left: 3px solid var(--section-color);
      padding: 0.4rem 0.75rem;
      margin-bottom: 1rem;
      border-radius: 0 4px 4px 0;
    }

    /* ── Item card ── */
    .item {
      background: #fff;
      border-radius: 6px;
      border: 1px solid #e0e0e0;
      border-left: 5px solid var(--urgency-color);
      padding: 1rem 1.25rem;
      margin-bottom: 0.75rem;
    }
    .item-title {
      font-size: 1rem;
      font-weight: 600;
      margin-bottom: 0.35rem;
    }
    .item-title a { color: #1a1a1a; text-decoration: none; }
    .item-title a:hover { text-decoration: underline; color: #0056b3; }

    .item-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem 1.25rem;
      font-size: 0.82rem;
      color: #444;
      margin-bottom: 0.6rem;
    }
    .item-meta span { display: flex; align-items: center; gap: 0.3rem; }
    .item-meta .label { font-weight: 600; color: #222; }

    .deadline-badge {
      display: inline-block;
      font-size: 0.78rem;
      font-weight: 700;
      padding: 0.15rem 0.55rem;
      border-radius: 4px;
      color: #fff;
      background: var(--urgency-color);
    }

    .item-summary {
      font-size: 0.88rem;
      color: #333;
      margin-top: 0.5rem;
      line-height: 1.55;
    }

    .item-links {
      margin-top: 0.6rem;
      font-size: 0.82rem;
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }
    .item-links a {
      color: #0056b3;
      text-decoration: none;
      border: 1px solid #c0d8f0;
      border-radius: 4px;
      padding: 0.15rem 0.5rem;
      background: #f0f6ff;
    }
    .item-links a:hover { background: #ddeeff; }

    /* ── Urgency colour tokens ── */
    .urgency-urgent  { --urgency-color: #C8102E; }
    .urgency-soon    { --urgency-color: #E87722; }
    .urgency-open    { --urgency-color: #2E7D32; }
    .urgency-ongoing { --urgency-color: #6B3A8B; }

    /* ── Sticky top bar (TOC + filter buttons) ── */
    .sticky-bar {
      position: sticky;
      top: 0;
      z-index: 100;
      box-shadow: 0 2px 6px rgba(0,0,0,0.07);
    }

    /* ── Urgency filter bar ── */
    .urgency-filters {
      background: #fff;
      border-bottom: 1px solid #ddd;
      padding: 0.55rem 2.5rem;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.4rem;
    }
    .urgency-filters .filter-label {
      font-size: 0.8rem;
      color: #555;
      margin-right: 0.2rem;
    }
    .filter-btn {
      font-size: 0.78rem;
      font-weight: 700;
      font-family: inherit;
      border: 2px solid var(--btn-color);
      border-radius: 20px;
      padding: 0.18rem 0.7rem;
      cursor: pointer;
      background: var(--btn-color);
      color: #fff;
      transition: background 0.15s, color 0.15s;
      line-height: 1.4;
    }
    .filter-btn:not(.active) {
      background: transparent;
      color: var(--btn-color);
    }
    @media (max-width: 600px) {
      .urgency-filters { padding: 0.5rem 1rem; }
    }

    /* ── Status pill (Canada.ca planned items) ── */
    .status-planned {
      font-size: 0.72rem;
      background: #e8e0f4;
      color: #4a2080;
      font-weight: 700;
      padding: 0.1rem 0.45rem;
      border-radius: 3px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    /* ── Empty section ── */
    .empty-note {
      color: #666;
      font-size: 0.88rem;
      font-style: italic;
      padding: 0.5rem 0;
    }

    /* ── Filtered items disclosure ── */
    .filtered-note {
      margin-top: 0.5rem;
      font-size: 0.8rem;
      color: #888;
    }
    .filtered-note summary {
      cursor: pointer;
      padding: 0.3rem 0;
      list-style: none;
    }
    .filtered-note summary::-webkit-details-marker { display: none; }
    .filtered-note summary::before { content: '+ '; }
    details[open].filtered-note summary::before { content: '- '; }
    .filtered-note ul {
      margin: 0.4rem 0 0.4rem 1.25rem;
      color: #aaa;
      line-height: 1.7;
    }

    /* ── NEW badge ── */
    .badge-new {
      display: inline-block;
      font-size: 0.65rem;
      font-weight: 800;
      background: #2E7D32;
      color: #fff;
      padding: 0.1rem 0.4rem;
      border-radius: 3px;
      letter-spacing: 0.06em;
      vertical-align: middle;
      margin-right: 0.35rem;
    }

    /* ── Star button ── */
    .item { position: relative; }
    .star-btn {
      position: absolute;
      top: 0.7rem;
      right: 0.75rem;
      background: none;
      border: none;
      cursor: pointer;
      font-size: 1.1rem;
      padding: 0;
      color: #ccc;
      line-height: 1;
      transition: color 0.15s;
    }
    .star-btn:hover, .star-btn.starred { color: #E8A020; }

    /* ── Change summary pills ── */
    .change-summary {
      display: flex;
      gap: 0.6rem;
      margin-top: 0.6rem;
      flex-wrap: wrap;
    }
    .change-pill {
      font-size: 0.78rem;
      font-weight: 600;
      padding: 0.15rem 0.65rem;
      border-radius: 20px;
    }
    .change-pill.pill-new    { background: rgba(255,255,255,0.2); color: #fff; }
    .change-pill.pill-urgent { background: #C8102E; color: #fff; }

    /* ── Search box ── */
    .search-wrap {
      margin-left: auto;
      display: flex;
      align-items: center;
    }
    .search-wrap input {
      font-family: inherit;
      font-size: 0.82rem;
      border: 1px solid #ccc;
      border-radius: 20px;
      padding: 0.2rem 0.8rem;
      width: 210px;
      outline: none;
    }
    .search-wrap input:focus { border-color: #26374A; box-shadow: 0 0 0 2px #26374a22; }
    @media (max-width: 600px) { .search-wrap input { width: 130px; } }

    /* ── Footer ── */
    .page-footer {
      text-align: center;
      font-size: 0.78rem;
      color: #888;
      padding: 2rem;
      border-top: 1px solid #ddd;
      margin-top: 2rem;
    }

    /* ── Collapsible sections ── */
    .section-header { cursor: pointer; user-select: none; }
    .section-header:hover { opacity: 0.85; }
    .section-toggle {
      margin-left: auto;
      font-size: 0.75rem;
      font-weight: 600;
      color: #fff;
      background: var(--section-color);
      border: 1px solid var(--section-color);
      border-radius: 4px;
      padding: 0.1rem 0.5rem;
      flex-shrink: 0;
      letter-spacing: 0.03em;
    }
    .section.collapsed .section-body { display: none; }

    @media (max-width: 600px) {
      .page-header { padding: 1.25rem; }
      .toc { padding: 0.5rem 1rem; }
      .content { padding: 0 0.75rem; }
      .urgency-filters { padding: 0.5rem 1rem; }
    }
  </style>
</head>
<body>

<!-- ── Page header ─────────────────────────────────────────────────── -->
<header class="page-header">
  <h1>Canadian Consultations Digest</h1>
  <div class="subtitle">{{ today.strftime('%A, %B %d, %Y') }} &nbsp;·&nbsp; Eight sources checked</div>
  <div class="total-badge">{{ total }} item{{ 's' if total != 1 else '' }} found</div>
  {% if new_count > 0 or urgent_count > 0 %}
  <div class="change-summary">
    {% if new_count > 0 %}
      <span class="change-pill pill-new">{{ new_count }} new since yesterday</span>
    {% endif %}
    {% if urgent_count > 0 %}
      <span class="change-pill pill-urgent">{{ urgent_count }} closing within 7 days</span>
    {% endif %}
  </div>
  {% endif %}
</header>

<!-- ── Sticky bar: TOC + urgency filters ───────────────────────────── -->
<div class="sticky-bar">
<nav class="toc">
  {% for sec in sections %}
    <a href="#{{ sec.id }}">{{ sec.icon }}: {{ sec.count }}</a>
  {% endfor %}
</nav>

<div class="urgency-filters">
  <span class="filter-label">Show:</span>
  <button class="filter-btn active" data-urgency="urgent" style="--btn-color:#C8102E">Closes &lt;7 days</button>
  <button class="filter-btn active" data-urgency="soon"   style="--btn-color:#E87722">&lt;30 days</button>
  <button class="filter-btn active" data-urgency="open"   style="--btn-color:#2E7D32">30+ days</button>
  <button class="filter-btn active" data-urgency="ongoing" style="--btn-color:#6B3A8B">No fixed deadline</button>
  <button class="filter-btn" id="starred-filter" style="--btn-color:#E8A020">&#9733; Starred</button>
  <div class="search-wrap">
    <input type="search" id="search-input" placeholder="Search consultations..." autocomplete="off">
  </div>
</div>
</div>{# end .sticky-bar #}

<!-- ── Sections ────────────────────────────────────────────────────── -->
<main class="content">

{% for sec in sections %}
<section class="section" id="{{ sec.id }}" style="--section-color: {{ sec.color }}">
  <div class="section-header">
    <span class="section-icon">{{ sec.icon }}</span>
    <h2>{{ sec.label }}</h2>
    <span class="section-count">{{ sec.count }} item{{ 's' if sec.count != 1 else '' }}</span>
    <span class="section-toggle">Hide</span>
  </div>

  <div class="section-body">

  {% if sec.note %}
  <div class="section-note">{{ sec.note }}</div>
  {% endif %}

  {% if sec.entries %}
    {% for item in sec.entries %}
    {# ── Determine primary link ── #}
    {% set primary_url = item.url or item.study_url or item.committee_url or '' %}

    <article class="item urgency-{{ item._urgency }}">

      <button class="star-btn" data-key="{{ item._key | e }}" title="Save for later">&#9734;</button>

      {# ── Title ── #}
      <div class="item-title">
        {% if item._is_new %}<span class="badge-new">NEW</span>{% endif %}
        {% if primary_url %}
          <a href="{{ primary_url }}" target="_blank" rel="noopener">{{ item.title }}</a>
        {% else %}
          {{ item.title }}
        {% endif %}
      </div>

      {# ── Meta row ── #}
      <div class="item-meta">

        {# Body (department / committee / ministry) #}
        {% set body = item.department or item.committee or '' %}
        {% if body %}
        <span>
          <span class="label">Body:</span>
          {{ body }}
          {% if item.acronym %} ({{ item.acronym }}){% endif %}
        </span>
        {% endif %}

        {# Deadline or Order of Reference #}
        {% if item.deadline and 'not specified' not in item.deadline|lower %}
          <span>
            <span class="label">Deadline:</span>
            <span class="deadline-badge">{{ item.deadline }}</span>
          </span>
        {% elif item.oor_label %}
          <span>
            <span class="label">Study referred:</span> {{ item.oor_label }}
          </span>
        {% endif %}

        {# Status pill for Canada.ca planned items #}
        {% if item.status and item.status != 'Open' %}
          <span class="status-planned">{{ item.status }}</span>
        {% endif %}

        {# Tracking number (Ontario Registry) #}
        {% if item.tracking %}
          <span><span class="label">Tracking:</span> {{ item.tracking }}</span>
        {% endif %}

      </div>

      {# ── Summary ── #}
      {% set summary = item.summary or '' %}
      {% if summary and summary != '(No description provided)' and summary != '(See original proposal for details.)' %}
      <div class="item-summary">{{ summary }}</div>
      {% endif %}

      {# ── Links ── #}
      <div class="item-links">
        {% if primary_url %}
          <a href="{{ primary_url }}" target="_blank" rel="noopener">View / Comment</a>
        {% endif %}
        {% if item.study_url and item.study_url != primary_url %}
          <a href="{{ item.study_url }}" target="_blank" rel="noopener">Study page</a>
        {% endif %}
        {% if item.external_url %}
          <a href="{{ item.external_url }}" target="_blank" rel="noopener">Also on ERO</a>
        {% endif %}
        {% if item.committee_url and item.committee_url != primary_url %}
          <a href="{{ item.committee_url }}" target="_blank" rel="noopener">Committee page</a>
        {% endif %}
      </div>

    </article>
    {% endfor %}

  {% else %}
    <p class="empty-note">No entries found from this source today.</p>
  {% endif %}

  {% if sec.filtered_count > 0 %}
  <details class="filtered-note">
    <summary>{{ sec.filtered_count }} item{{ 's' if sec.filtered_count != 1 else '' }} not shown (matched keyword filter)</summary>
    <ul>
      {% for title in sec.filtered_titles %}
      <li>{{ title }}</li>
      {% endfor %}
    </ul>
  </details>
  {% endif %}

  </div>{# end .section-body #}

</section>
{% endfor %}

</main>

<footer class="page-footer">
  Generated {{ today.strftime('%B %d, %Y') }} &nbsp;·&nbsp;
  Sources: Canada Gazette Part&nbsp;I &middot; Canada.ca &middot;
  House of Commons &middot; Senate of Canada &middot;
  Ontario Regulatory Registry &middot; Ontario.ca &middot; Ontario Legislature &middot;
  Department of Finance Canada
</footer>

<script>
  // ── State ─────────────────────────────────────────────────────────────────
  var activeUrgencies = new Set(['urgent', 'soon', 'open', 'ongoing']);
  var showOnlyStarred = false;

  // ── Starred items (localStorage) ──────────────────────────────────────────
  function isStarred(key) { return localStorage.getItem('star::' + key) === '1'; }
  function toggleStar(key) {
    if (isStarred(key)) { localStorage.removeItem('star::' + key); }
    else                { localStorage.setItem('star::' + key, '1'); }
  }

  document.querySelectorAll('.star-btn').forEach(function(btn) {
    if (isStarred(btn.dataset.key)) {
      btn.innerHTML = '&#9733;';
      btn.classList.add('starred');
    }
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      toggleStar(btn.dataset.key);
      var starred = isStarred(btn.dataset.key);
      btn.classList.toggle('starred', starred);
      btn.innerHTML = starred ? '&#9733;' : '&#9734;';
      updateVisibility();
    });
  });

  // ── Master visibility function ─────────────────────────────────────────────
  function updateVisibility() {
    var term = (document.getElementById('search-input').value || '').toLowerCase().trim();
    document.querySelectorAll('.item').forEach(function(item) {
      var urgencyClass = Array.from(item.classList)
            .find(function(c) { return c.startsWith('urgency-'); }) || '';
      var urgency   = urgencyClass.replace('urgency-', '');
      var starBtn   = item.querySelector('.star-btn');
      var urgencyOk = activeUrgencies.has(urgency);
      var textOk    = !term || item.textContent.toLowerCase().includes(term);
      var starOk    = !showOnlyStarred || (starBtn && starBtn.classList.contains('starred'));
      item.style.display = (urgencyOk && textOk && starOk) ? '' : 'none';
    });
  }

  // ── Urgency filter buttons ─────────────────────────────────────────────────
  document.querySelectorAll('.filter-btn[data-urgency]').forEach(function(btn) {
    if (btn.id === 'starred-filter') return;
    btn.addEventListener('click', function() {
      btn.classList.toggle('active');
      if (btn.classList.contains('active')) { activeUrgencies.add(btn.dataset.urgency); }
      else                                  { activeUrgencies.delete(btn.dataset.urgency); }
      updateVisibility();
    });
  });

  // ── Starred filter ─────────────────────────────────────────────────────────
  document.getElementById('starred-filter').addEventListener('click', function() {
    showOnlyStarred = !showOnlyStarred;
    this.classList.toggle('active', showOnlyStarred);
    updateVisibility();
  });

  // ── Search ─────────────────────────────────────────────────────────────────
  document.getElementById('search-input').addEventListener('input', updateVisibility);

  // ── Collapsible section headers ────────────────────────────────────────────
  document.querySelectorAll('.section-header').forEach(function(header) {
    header.addEventListener('click', function() {
      var section = header.closest('.section');
      var toggle  = header.querySelector('.section-toggle');
      section.classList.toggle('collapsed');
      toggle.textContent = section.classList.contains('collapsed') ? 'Show' : 'Hide';
    });
  });
</script>

</body>
</html>
"""

# ── Render and save ───────────────────────────────────────────────────────────

def generate(output_path: str | None = None) -> str:
    """Run all scrapers, render the HTML, save it, and return the file path."""
    today = date.today()
    if output_path is None:
        output_path = f"digest_{today.isoformat()}.html"

    print(f"\nGenerating digest for {today.strftime('%B %d, %Y')} ...\n")
    data = collect_all()

    env  = Environment(loader=BaseLoader())
    tmpl = env.from_string(TEMPLATE)
    html = tmpl.render(**data)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    path = generate()
    print(f"\nDone! Digest saved to: {path}")
    print(f"Open it by double-clicking the file, or run:")
    print(f"  start {path}")
