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
from datetime import date, datetime, timedelta
from jinja2 import Environment, BaseLoader

# ── Import all seven scrapers ─────────────────────────────────────────────────
import fetch_gazette
import fetch_canada_ca
import fetch_hoc
import fetch_senate
import fetch_ontario
import fetch_ontario_ca
import fetch_ola

# ── Content filter ───────────────────────────────────────────────────────────
#
# Consultations whose title contains any of these phrases (case-insensitive)
# are hidden from the main digest and shown only as a collapsed count.
# Add or remove phrases here to tune what gets filtered out.

BLOCKLIST = [
    # Species-at-risk documents
    "recovery strategy",
    "management plan for",
    # Technical feed / drug / chemical regulations
    "feed ingredient",
    "livestock feed",
    "veterinary drug",
    "maximum residue limit",
    "residue limit",
    "pest control product",
]


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
                "Senate committees accept written briefs at any time during a study — "
                "no fixed deadline. Email ctm@sen.parl.gc.ca with the study title and "
                "committee name. Showing studies referred in the last 90 days first."
            ),
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

    return {"sections": sections, "total": total, "today": date.today()}


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

    /* ── Footer ── */
    .page-footer {
      text-align: center;
      font-size: 0.78rem;
      color: #888;
      padding: 2rem;
      border-top: 1px solid #ddd;
      margin-top: 2rem;
    }

    @media (max-width: 600px) {
      .page-header { padding: 1.25rem; }
      .toc { padding: 0.5rem 1rem; }
      .content { padding: 0 0.75rem; }
    }
  </style>
</head>
<body>

<!-- ── Page header ─────────────────────────────────────────────────── -->
<header class="page-header">
  <h1>Canadian Consultations Digest</h1>
  <div class="subtitle">{{ today.strftime('%A, %B %d, %Y') }} &nbsp;·&nbsp; Seven sources checked</div>
  <div class="total-badge">{{ total }} item{{ 's' if total != 1 else '' }} found</div>
</header>

<!-- ── Urgency legend & table of contents ──────────────────────────── -->
<nav class="toc">
  {% for sec in sections %}
    <a href="#{{ sec.id }}">{{ sec.icon }}: {{ sec.count }}</a>
  {% endfor %}
  &nbsp;|&nbsp;
  <span style="font-size:0.82rem;color:#555;padding:0.2rem 0;line-height:1.6">
    <span style="color:#C8102E;font-weight:700;">&#9646;</span> Closes &lt;7 days &nbsp;
    <span style="color:#E87722;font-weight:700;">&#9646;</span> &lt;30 days &nbsp;
    <span style="color:#2E7D32;font-weight:700;">&#9646;</span> Open &nbsp;
    <span style="color:#6B3A8B;font-weight:700;">&#9646;</span> No fixed deadline
  </span>
</nav>

<!-- ── Sections ────────────────────────────────────────────────────── -->
<main class="content">

{% for sec in sections %}
<section class="section" id="{{ sec.id }}" style="--section-color: {{ sec.color }}">
  <div class="section-header">
    <span class="section-icon">{{ sec.icon }}</span>
    <h2>{{ sec.label }}</h2>
    <span class="section-count">{{ sec.count }} item{{ 's' if sec.count != 1 else '' }}</span>
  </div>

  {% if sec.note %}
  <div class="section-note">{{ sec.note }}</div>
  {% endif %}

  {% if sec.entries %}
    {% for item in sec.entries %}
    {# ── Determine primary link ── #}
    {% set primary_url = item.url or item.study_url or item.committee_url or '' %}

    <article class="item urgency-{{ item._urgency }}">

      {# ── Title ── #}
      <div class="item-title">
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

</section>
{% endfor %}

</main>

<footer class="page-footer">
  Generated {{ today.strftime('%B %d, %Y') }} &nbsp;·&nbsp;
  Sources: Canada Gazette Part&nbsp;I &middot; Canada.ca &middot;
  House of Commons &middot; Senate of Canada &middot;
  Ontario Regulatory Registry &middot; Ontario.ca &middot; Ontario Legislature
</footer>

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
