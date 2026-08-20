#!/usr/bin/env python3
"""
Shortlist page generator — renders scored properties into a self-contained
HTML page hosted on GitHub Pages. George opens the link, browses, taps
feedback, favourites properties, and leaves comments. Saves are confirmed by
the Cloudflare D1 backend, with an optional display name and no login.

Usage:
    from shortlist import generate_shortlist
    generate_shortlist(properties)                    # saves to docs/index.html
    generate_shortlist(properties)                    # all properties (default)
    generate_shortlist(properties, max_properties=20) # top 20 only

Standalone:
    python3 shortlist.py                  # generate from latest search results
    python3 shortlist.py --open           # generate and open in browser
"""

import json
import html as html_mod
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from availability import availability_status, is_archived_status, status_label

load_dotenv()

BASE_DIR = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "data" / "listings"
DOCS_DIR = BASE_DIR / "docs"
DOCS_DIR.mkdir(exist_ok=True)

# Baseline of what George last received. "New" = source_ids not in here.
# Updated ONLY via `shortlist.py --mark-sent`, so preview re-renders don't
# poison the new set. Seed once from the last shortlist George actually saw.
LAST_SENT_FILE = BASE_DIR / "data" / "last_sent.json"

# Sources may be suppressed only when the entire adapter is intentionally
# disabled. REA is now quality-gated at ingestion and should remain visible.
SUPPRESSED_SOURCES = set()

AUTOMATED_FEED_NAMES = frozenset({
    "Domain Web",
    "Farmbuy",
    "Elders",
    "REA (Apify)",
    "Email Alerts",
})


def _automated_feed_count(source_report):
    """Count production feeds attempted in a search run."""
    return sum(name in source_report for name in AUTOMATED_FEED_NAMES)


def _is_suppressed_property(prop):
    """Hide known-low-quality sources and CRE records without a real listing id."""
    if prop.get("source") in SUPPRESSED_SOURCES:
        return True
    if prop.get("source") == "rea_apify":
        # Older Actor rows lacked a usable detail/search URL. New ingestion
        # supplies a canonical URL or an exact filtered-search fallback.
        return not bool(str(prop.get("listing_url") or "").strip())
    if prop.get("source") == "listing_loop":
        has_address = bool(str(prop.get("address") or "").strip())
        has_property_detail = any(
            prop.get(field) not in (None, "", 0)
            for field in ("price", "land_acres", "bedrooms", "headline", "description")
        )
        return not (has_address and has_property_detail)
    if prop.get("source") == "cre":
        path = urlparse(prop.get("listing_url") or "").path.rstrip("/")
        # CRE's canonical property pages end in a numeric listing id. Older
        # alert parsing fabricated slug-only URLs, which lead to a 404.
        return not bool(re.search(r"-\d{7,}$", path))
    return False


def _visible_props(properties, max_properties=None):
    """Current listings shown in the main shortlist."""
    visible = []
    for original in properties:
        if _is_suppressed_property(original):
            continue
        prop = dict(original)
        prop["status"] = availability_status(
            prop,
            missing_from_latest=bool(prop.get("missing_from_latest")),
            missing_days=prop.get("last_seen_days") or 0,
        )
        if not is_archived_status(prop["status"]):
            visible.append(prop)
    return visible[:max_properties] if max_properties else visible


def _archived_props(properties):
    """Unavailable listings retained so their history and feedback stay useful."""
    archived = []
    for original in properties:
        if _is_suppressed_property(original):
            continue
        prop = dict(original)
        prop["status"] = availability_status(
            prop,
            missing_from_latest=bool(prop.get("missing_from_latest")),
            missing_days=prop.get("last_seen_days") or 0,
        )
        if is_archived_status(prop["status"]):
            archived.append(prop)
    return sorted(archived, key=lambda prop: prop.get("last_seen_days") or 0)


def _canonical_property_key(prop):
    """Stable cross-source identity for the same advertised street address."""
    address = re.sub(r"[^a-z0-9]+", "", str(prop.get("address") or "").lower())
    if address:
        return f"address:{address}"
    return f"source:{prop.get('source') or ''}:{prop.get('source_id') or prop.get('id') or ''}"


def _property_quality(prop):
    """Prefer active, complete canonical cards when sources advertise the same place."""
    status = prop.get("status") or "active"
    active_rank = 0 if is_archived_status(status) else 1
    explicitly_active = 1 if status == "active" else 0
    completeness = sum(
        prop.get(field) not in (None, "", 0, [])
        for field in (
            "price", "land_acres", "bedrooms", "bathrooms", "headline",
            "description", "photo_url", "listing_url", "lat", "lng",
        )
    )
    source_rank = 1 if prop.get("source") == "domain_web" else 0
    score = float((prop.get("score") or {}).get("pct") or 0)
    return active_rank, explicitly_active, completeness, source_rank, score


def _dedupe_cross_source(properties):
    """Collapse exact-address cross-source duplicates without merging same-source lots."""
    groups = {}
    order = []
    for prop in properties:
        key = _canonical_property_key(prop)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(prop)

    deduped = []
    for key in order:
        group = groups[key]
        sources = {prop.get("source") for prop in group}
        if len(group) == 1 or len(sources) <= 1 or key.startswith("source:"):
            deduped.extend(group)
            continue
        deduped.append(max(group, key=_property_quality))
    return deduped


def _partition_props(properties, max_properties=None):
    """Split one deduplicated inventory into active and archived cards."""
    candidates = _visible_props(properties) + _archived_props(properties)
    canonical = _dedupe_cross_source(candidates)
    all_active = [prop for prop in canonical if not is_archived_status(prop.get("status"))]
    archived = [prop for prop in canonical if is_archived_status(prop.get("status"))]
    if max_properties:
        return all_active[:max_properties], [], len(all_active)
    return all_active, archived, len(all_active)


def _load_last_sent_ids():
    """Source_ids George last received; empty set if no baseline yet."""
    if not LAST_SENT_FILE.exists():
        print("WARNING: no data/last_sent.json baseline — '0 new' until --mark-sent",
              file=sys.stderr)
        return set()
    try:
        with open(LAST_SENT_FILE) as f:
            return set(json.load(f).get("source_ids", []))
    except (json.JSONDecodeError, IOError):
        return set()

NOTES_URL = os.getenv(
    "NOTES_SCRIPT_URL",
    "https://bolt-hole-backend.karl-582.workers.dev",
)

# Readable labels for score breakdown keys
SCORE_LABELS = {
    "water": "Water",
    "terrain": "Terrain",
    "seclusion": "Seclusion",
    "house_quality": "House",
    "drive_time_bonus": "Drive time",
    "national_park_adjacent": "National park",
    "carbon_eligible": "Carbon",
    "convenience": "Convenience",
}


def _escape(text):
    return html_mod.escape(str(text)) if text else ""


def _score_color(pct):
    if pct >= 70:
        return "#166534", "#dcfce7"
    if pct >= 55:
        return "#1e40af", "#dbeafe"
    if pct >= 40:
        return "#92400e", "#fef3c7"
    return "#64748b", "#f1f5f9"


def _drive_display(mins):
    if mins is None:
        return None, None, None
    hours = int(mins // 60)
    m = int(mins - hours * 60)
    label = f"{hours}h{m:02d}m"
    if hours < 3:
        return label, "#166534", "#dcfce7"
    if hours < 4:
        return label, "#92400e", "#fef3c7"
    return label, "#991b1b", "#fee2e2"


# Corridor median $/acre from 974 historical sales (PSI data)
_CORRIDOR_PPA = {
    "Bathurst Regional": 13472, "Goulburn Mulwaree": 13333,
    "Hilltops": 16667, "Lithgow": 9596, "Mid Western Regional": 9598,
    "Oberon": 17000, "Orange": 33611, "Queanbeyan-Palerang": 17451,
    "Snowy Monaro Regional": 8586, "Upper Lachlan": 10891,
    "Wingecarribee": 18333, "Wollondilly": 40000, "Yass Valley": 15138,
}
_OVERALL_MEDIAN_PPA = 12247  # fallback

# Postcode → corridor lookup
_PC_TO_CORRIDOR = {}
for _pc in ["2795", "2798", "2799", "2800"]:
    _PC_TO_CORRIDOR[_pc] = "Bathurst Regional"
for _pc in ["2580"]:
    _PC_TO_CORRIDOR[_pc] = "Goulburn Mulwaree"
for _pc in ["2583", "2584", "2586", "2587", "2594"]:
    _PC_TO_CORRIDOR[_pc] = "Hilltops"
for _pc in ["2790", "2791"]:
    _PC_TO_CORRIDOR[_pc] = "Lithgow"
for _pc in ["2799"]:
    _PC_TO_CORRIDOR[_pc] = "Mid Western Regional"
for _pc in ["2787"]:
    _PC_TO_CORRIDOR[_pc] = "Oberon"
for _pc in ["2620", "2621", "2622", "2623"]:
    _PC_TO_CORRIDOR[_pc] = "Queanbeyan-Palerang"
for _pc in ["2630", "2631"]:
    _PC_TO_CORRIDOR[_pc] = "Snowy Monaro Regional"
for _pc in ["2581", "2582"]:
    _PC_TO_CORRIDOR[_pc] = "Upper Lachlan"
for _pc in ["2575", "2576", "2577"]:
    _PC_TO_CORRIDOR[_pc] = "Wingecarribee"
for _pc in ["2578", "2579"]:
    _PC_TO_CORRIDOR[_pc] = "Wollondilly"
for _pc in ["2582"]:
    _PC_TO_CORRIDOR[_pc] = "Yass Valley"


def _value_badge(price, land_acres, postcode):
    """Return ($/acre label, badge text, badge color, badge bg) or Nones."""
    if not price or not land_acres or land_acres <= 0:
        return None, None, None, None
    ppa = price / land_acres
    ppa_label = f"${ppa:,.0f}/ac"
    budget_pct = f"{price / 20000:.0f}% of budget"

    corridor = _PC_TO_CORRIDOR.get(postcode, "")
    median = _CORRIDOR_PPA.get(corridor, _OVERALL_MEDIAN_PPA)

    ratio = ppa / median
    if ratio <= 0.8:
        return ppa_label, "Good Value", "#166534", "#dcfce7"
    elif ratio <= 1.2:
        return ppa_label, "Fair", "#1e40af", "#dbeafe"
    else:
        return ppa_label, "Premium", "#92400e", "#fef3c7"


def generate_shortlist(
    properties,
    search_date=None,
    max_properties=None,
    output_path=None,
    source_report=None,
):
    if search_date is None:
        search_date = datetime.now().strftime("%d %B %Y")
    if output_path is None:
        output_path = DOCS_DIR / "index.html"

    active_props, archived_props, total_found = _partition_props(properties, max_properties)
    props = active_props + archived_props
    total_shown = len(active_props)
    archived_count = len(archived_props)
    source_report = source_report or {}

    # "New" = anything George hasn't seen since his last send. Single source of
    # truth (data/last_sent.json) so the count, the NEW badge, and the New sort
    # all agree — unlike the old single-previous-file diff, which miscounted
    # every carried-over/sheet listing as new.
    last_sent_ids = _load_last_sent_ids()
    new_ids = {
        pid for p in active_props
        if (pid := (p.get("source_id") or p.get("id"))) and pid not in last_sent_ids
    }

    # ── Build cards HTML ──────────────────────────────────────────────────
    cards_html = []
    for i, p in enumerate(props):
        archived = is_archived_status(p.get("status"))
        score = p.get("score", {})
        pct = score.get("pct", 0)
        breakdown = score.get("breakdown", {})
        max_possible = score.get("max_possible", 100)
        sc_color, sc_bg = _score_color(pct)

        price = p.get("price")
        price_str = f"${price:,.0f}" if price else _escape(p.get("display_price") or "Price not disclosed")

        acres = p.get("land_acres")
        acres_str = f"{acres:.0f} acres" if acres else "Acreage not stated"

        beds = p.get("bedrooms")
        baths = p.get("bathrooms")
        bed_bath = "Bedrooms not stated"
        if beds:
            bed_bath = f"{beds} bed"
            if baths:
                bed_bath += f" / {baths} bath"

        drive_mins = p.get("drive_time_minutes")
        drive_label, drive_color, drive_bg = _drive_display(drive_mins)
        drive_html = ""
        if drive_label:
            drive_html = f'<span class="stat-badge" style="color:{drive_color};background:{drive_bg};">{drive_label}</span>'

        # Sort key for $/acre; 0 sentinel -> JS pushes to end
        ppa = (price / acres) if (price and acres) else 0

        headline = _escape(p.get("headline", ""))
        address = _escape(p.get("address", ""))
        normalized_description = re.sub(r"\s+", " ", p.get("description", "")).strip()
        description = _escape(normalized_description[:400])
        if len(normalized_description) > 400:
            description += "..."

        listing_url = _escape(p.get("listing_url", "#"))
        photo_url = p.get("photo_url")

        photo_html = ""
        if photo_url:
            photo_html = f'<div class="card-photo"><img src="{_escape(photo_url)}" alt="" loading="lazy" width="720" height="540" /></div>'

        tags = p.get("tags", [])
        tags_html = ""
        if tags:
            pills = "".join(f'<span class="tag">{_escape(t.replace("_", " ").title())}</span>' for t in tags[:6])
            tags_html = f'<div class="tags">{pills}</div>'

        # Value badge
        ppa_label, val_text, val_color, val_bg = _value_badge(
            p.get("price"), p.get("land_acres"), p.get("postcode", ""))
        value_html = ""
        if ppa_label:
            value_html = f'<span class="stat-badge" style="color:{val_color};background:{val_bg};">{val_text} &middot; {ppa_label}</span>'

        stats_parts = []
        if acres_str:
            stats_parts.append(f'<span class="stat">{acres_str}</span>')
        if bed_bath:
            stats_parts.append(f'<span class="stat">{bed_bath}</span>')
        if drive_html:
            stats_parts.append(drive_html)
        if value_html:
            stats_parts.append(value_html)
        missing_from_latest = p.get("missing_from_latest")
        last_seen_days = p.get("last_seen_days") or 0
        if missing_from_latest:
            if last_seen_days == 0:
                seen_label = "earlier today"
            elif last_seen_days == 1:
                seen_label = "yesterday"
            else:
                seen_label = f"{last_seen_days}d ago"
            stats_parts.append(
                f'<span class="stat stat-stale" title="Missing from this week\'s scrape — may have sold or the source throttled">last seen {seen_label}</span>'
            )
        first_seen_days = p.get("first_seen_days")
        # Cap at 7d: anything older risks being a sheet-bootstrap artefact
        # (the perpetual DB went live 2026-04-23, so pre-existing listings
        # all share that date as first_seen even though they're truly older).
        # Once the bootstrap cohort ages out of the 21-day window, this cap
        # can be relaxed — every first_seen will then be genuine.
        if first_seen_days is not None and first_seen_days <= 7:
            if first_seen_days == 0:
                first_label = "spotted today"
            elif first_seen_days == 1:
                first_label = "spotted yesterday"
            else:
                first_label = f"spotted {first_seen_days}d ago"
            stats_parts.append(
                f'<span class="stat stat-fresh" title="First time this listing appeared in our scrapes">{first_label}</span>'
            )
        stats_row = " ".join(stats_parts)

        prop_id = _escape(p.get("source_id") or p.get("id") or str(i))

        # Score breakdown rows
        breakdown_rows = ""
        for key, val in breakdown.items():
            label = SCORE_LABELS.get(key, key.replace("_", " ").title())
            # Find the max weight for this category from criteria
            # We approximate: total max_possible is 100, breakdown values are raw points
            bar_pct = min(100, (val / max_possible) * 100 * (100 / max(pct, 1)) if pct > 0 else 0)
            # Simpler: show raw score vs what's possible (approximate from weight)
            breakdown_rows += f'''<div class="bd-row">
                <span class="bd-label">{label}</span>
                <span class="bd-bar"><span class="bd-fill" style="width:{min(val * 4, 100):.0f}%;background:{sc_color};"></span></span>
                <span class="bd-val">{val:.0f}</span>
            </div>'''

        stale_attr = 'data-stale="1"' if missing_from_latest else ''
        archive_class = " archived-card" if archived else ""
        status_badge = (
            f'<span class="availability-badge">{_escape(status_label(p.get("status")))}</span>'
            if archived else ""
        )
        rank_control = (
            ''
            if archived else
            f'<button type="button" class="rank-badge" style="background:{sc_color};" onclick="panMapToCard({i})" title="Find property {i+1} on the map" aria-label="Find property {i+1} on the map">#{i+1}</button>'
        )
        # Badge matches the count: new = not seen since last send (a carried-over
        # listing can still be genuinely new to George).
        is_new = 1 if prop_id in new_ids else 0
        cards_html.append(f'''
        <div class="card{archive_class}" id="card-{i}" data-idx="{i}" data-property-id="{prop_id}" data-score="{pct:.1f}" data-price="{price or 0}" data-acres="{acres or 0}" data-drive="{drive_mins or 9999}" data-new="{is_new}" data-ppa="{ppa:.0f}" {stale_attr}>
            {photo_html}
            <div class="card-body">
                <div class="card-top-row">
                    <div class="card-header">
                        {rank_control}
                        <span class="price">{price_str}</span>
                        {status_badge}{"<span class='new-badge'>NEW</span>" if is_new else ""}<button type="button" class="score-badge" id="score-{i}" style="color:{sc_color};background:{sc_bg};" onclick="toggleBreakdown({i})" title="Tap to see score breakdown" aria-expanded="false" aria-controls="breakdown-{i}">{pct:.0f}% match</button>
                    </div>
                    <button type="button" class="fav-btn" id="fav-{i}" onclick="toggleFavourite({i}, '{prop_id}')" title="Favourite" aria-label="Favourite property {i + 1}" aria-pressed="false">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
                    </button>
                </div>
                <div class="breakdown" id="breakdown-{i}" style="display:none;">
                    {breakdown_rows}
                </div>
                <div class="headline">{headline}</div>
                <div class="address">{address}</div>
                <div class="stats">{stats_row}</div>
                <div class="description">{description}</div>
                {tags_html}
                <div class="actions">
                    <a href="{listing_url}" target="_blank" rel="noopener" class="btn btn-view">{"Last listing" if archived else "View listing"}</a>
                    <div class="feedback" id="feedback-{i}">
                        <button type="button" class="btn btn-love" aria-pressed="false" data-reaction="love" onclick="sendFeedback({i}, '{prop_id}', 'love')">Love it</button>
                        <button type="button" class="btn btn-interesting" aria-pressed="false" data-reaction="interesting" onclick="sendFeedback({i}, '{prop_id}', 'interesting')">Interesting</button>
                        <button type="button" class="btn btn-pass" aria-pressed="false" data-reaction="pass" onclick="sendFeedback({i}, '{prop_id}', 'pass')">Not for me</button>
                    </div>
                </div>
                <div class="notes-section" id="notes-section-{i}" data-property-id="{prop_id}">
                    <button type="button" class="notes-pill notes-pill-empty" onclick="toggleNotes({i})" aria-expanded="false" aria-controls="notes-drawer-{i}">+ note</button>
                    <div class="notes-drawer" id="notes-drawer-{i}" style="display:none;">
                        <div class="notes-list" id="notes-list-{i}"></div>
                        <div class="notes-input-row">
                            <input type="text" class="notes-input" id="notes-input-{i}" name="property-note-{i}" autocomplete="off" aria-label="Add a note for this property" placeholder="Add a note…" maxlength="500" onkeydown="noteKeydown(event, {i}, '{prop_id}')">
                            <button type="button" class="notes-post" id="notes-post-{i}" onclick="submitNote({i}, '{prop_id}')">Post</button>
                        </div>
                    </div>
                </div>
                <div class="feedback-confirmation" id="confirm-{i}" role="status" aria-live="polite" style="display:none;"></div>
            </div>
        </div>''')

    all_cards = "\n".join(cards_html)

    # ── Summary ───────────────────────────────────────────────────────────
    if max_properties and total_found > max_properties:
        showing = f"Showing top {max_properties} of {total_found} matches"
    else:
        showing = f"{total_found} properties matched your criteria"

    best = active_props[0] if active_props else None
    top_match = ""
    if best:
        top_match = f'Top match: {_escape(best.get("headline", "")[:60])} ({best["score"]["pct"]:.0f}%)'

    new_count = len(new_ids)

    notes_url_js = _escape(NOTES_URL) if NOTES_URL else ""

    # ── Map markers JSON ──────────────────────────────────────────────────
    mapped_props = [(i, p) for i, p in enumerate(active_props) if p.get("lat") and p.get("lng")]
    total_count = len(active_props)
    mapped_count = len(mapped_props)
    missing_count = total_count - mapped_count
    markers_json = json.dumps([
        {
            "idx": i,
            "lat": p["lat"],
            "lng": p["lng"],
            "suburb": p.get("suburb", ""),
            "price": f"${p['price']:,.0f}" if p.get("price") else p.get("display_price", "?"),
            "pct": p["score"]["pct"],
            "acres": f"{p['land_acres']:.0f}ac" if p.get("land_acres") else "",
        }
        for i, p in mapped_props
    ])
    if missing_count > 0:
        map_coverage_badge = (
            f'<span class="map-coverage">{mapped_count} of {total_count} on map '
            f'<span class="map-coverage-missing" title="Properties without geocoded coordinates">'
            f'· {missing_count} missing coords</span></span>'
        )
    else:
        map_coverage_badge = f'<span class="map-coverage">{mapped_count} on map</span>'

    # ── Full page HTML ────────────────────────────────────────────────────
    page_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bolt Hole — Property Shortlist</title>
    <link rel="icon" href="design-system/assets/logo-mark.png" />
    <script>const initialView = new URLSearchParams(location.search).get('view'); if (initialView === 'past' || initialView === 'archived') document.documentElement.classList.add('past-view'); else document.documentElement.classList.add('task-view-' + (['saved', 'all'].includes(initialView) ? initialView : 'review'));</script>
    <link rel="preconnect" href="https://unpkg.com" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
    <script src="site-state.js" defer></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&display=swap');

        :root {{
            --limestone: #f5f0e8;
            --bark: #1e293b;
            --eucalyptus: #4A7C6B;
            --slate: #64748b;
            --light-border: #e2e8f0;
            --fav-gold: #eab308;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        button, a, select {{ touch-action: manipulation; }}
        :focus-visible {{ outline: 3px solid var(--eucalyptus); outline-offset: 3px; }}

        body {{
            font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--limestone);
            color: var(--bark);
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }}

        .container {{
            max-width: 640px;
            margin: 0 auto;
            padding: 24px 16px 80px; /* extra bottom for progress bar */
        }}

        /* ── Header ─────────────────────────────── */
        .header {{ text-align: center; padding: 32px 0 24px; }}
        .header .brand {{
            font-size: 11px; font-weight: 600; letter-spacing: 2.5px;
            color: var(--slate); text-transform: uppercase; margin-bottom: 6px;
        }}
        .header h1 {{
            font-family: 'DM Serif Display', Georgia, serif;
            font-size: 28px; font-weight: 400; color: var(--bark); margin-bottom: 4px;
        }}
        .header .date {{ font-size: 14px; color: var(--slate); }}
        .header .freshness {{ font-size: 12px; color: var(--slate); margin-top: 6px; opacity: 0.8; }}

        /* ── Summary ────────────────────────────── */
        .summary {{
            background: #fff; border: 1px solid var(--light-border);
            border-radius: 10px; padding: 16px 20px; margin-bottom: 28px;
        }}
        .summary .count {{ font-size: 15px; color: var(--bark); font-weight: 500; }}
        .summary .top {{ font-size: 13px; color: var(--slate); margin-top: 4px; }}
        .task-views {{
            display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
            margin: -16px 0 0; padding: 8px; border-radius: 12px;
            background: #EDEBE7;
        }}
        .task-views button {{
            min-height: 48px; display: inline-flex; flex-direction: column;
            align-items: center; justify-content: center; padding: 8px;
            border: 0; border-radius: 8px; background: transparent;
            color: var(--slate); font: inherit; font-size: 13px;
            font-weight: 600; cursor: pointer; text-align: center;
        }}
        .task-view-count {{
            display: block; margin-top: 4px; font-size: 13px;
            font-weight: 500; line-height: 1.2; opacity: 0.75;
        }}
        html.task-view-review .task-views [data-view="review"],
        html.task-view-saved .task-views [data-view="saved"],
        html.task-view-all .task-views [data-view="all"] {{
            background: #fff; color: var(--eucalyptus);
        }}
        .past-listings-link {{
            display: flex; align-items: center; justify-content: space-between;
            gap: 16px; margin: 16px 0 24px; padding: 16px 4px;
            border-bottom: 1px solid #E2DDD6; color: var(--slate);
            text-decoration: none; font-size: 13px;
        }}
        .past-listings-link strong {{ color: #2D5A4A; font-size: 13px; }}
        .past-listings-link .past-listings-arrow {{ white-space: nowrap; }}
        .past-listings-link:hover,
        html.past-view .past-listings-link {{ color: var(--eucalyptus); }}
        html.past-view .past-listings-link strong {{ color: var(--eucalyptus); }}
        html.past-view .past-listings-link {{ border-bottom-color: var(--eucalyptus); }}
        .past-summary {{
            display: none; background: #fff; border: 1px solid #d6c7ad;
            border-radius: 10px; padding: 16px 20px; margin-bottom: 18px;
        }}
        .past-summary strong, .past-summary span {{ display: block; }}
        .past-summary span {{ margin-top: 4px; color: var(--slate); font-size: 13px; }}
        .view-empty {{
            display: none; background: #fff; border: 1px dashed var(--light-border);
            border-radius: 10px; padding: 28px 20px; margin-bottom: 24px;
            text-align: center; color: var(--slate); font-size: 13px;
        }}

        /* ── Sort bar ──────────────────────────── */
        .sort-bar {{
            display: flex; align-items: center; gap: 6px;
            padding: 10px 16px; margin-bottom: 16px;
            overflow-x: auto; scrollbar-width: none;
            -webkit-overflow-scrolling: touch;
        }}
        .sort-bar::-webkit-scrollbar {{ display: none; }}
        .sort-label {{
            font-size: 11px; font-weight: 600; color: var(--slate);
            text-transform: uppercase; letter-spacing: 0.5px;
            white-space: nowrap; margin-right: 4px;
        }}
        .sort-btn {{
            font-family: Inter, -apple-system, sans-serif;
            font-size: 12px; font-weight: 500; padding: 6px 14px;
            border-radius: 20px; border: 1px solid var(--light-border);
            background: #fff; color: var(--slate); cursor: pointer;
            white-space: nowrap; transition: background-color 0.15s, border-color 0.15s, color 0.15s;
        }}
        .sort-btn:hover {{ border-color: var(--eucalyptus); color: var(--bark); }}
        .sort-btn.active {{
            background: var(--eucalyptus); color: #fff;
            border-color: var(--eucalyptus);
        }}

        /* ── NEW badge ─────────────────────────── */
        .new-badge {{
            display: inline-block; font-size: 10px; font-weight: 700;
            padding: 2px 7px; border-radius: 4px;
            background: #dbeafe; color: #1d4ed8;
            letter-spacing: 0.5px; margin-right: 6px;
            vertical-align: middle;
        }}

        /* ── Rank badge (matches map pin number/colour) ─── */
        .rank-badge {{
            display: inline-flex; align-items: center; justify-content: center;
            min-width: 40px; height: 40px; padding: 0 9px; border: 0;
            font-size: 12px; font-weight: 700; color: #fff;
            border-radius: 20px; margin-right: 4px; font-family: inherit;
            cursor: pointer; user-select: none;
            box-shadow: 0 1px 2px rgba(0,0,0,0.15);
            transition: transform 0.15s, box-shadow 0.15s;
            vertical-align: middle;
        }}
        .rank-badge:hover {{
            transform: translateY(-1px);
            box-shadow: 0 2px 5px rgba(0,0,0,0.25);
        }}
        .rank-badge:active {{ transform: translateY(0); }}

        /* ── Map ────────────────────────────────── */
        .map-container {{
            background: #fff; border: 1px solid var(--light-border);
            border-radius: 10px; margin-bottom: 28px;
            /* overflow:hidden removed — iOS Safari clips Leaflet touch events with border-radius */
            -webkit-overflow-scrolling: touch;
            position: relative;
        }}
        .map-container #shortlist-map {{
            border-radius: 0 0 10px 10px; /* rounded bottom corners without clipping touch */
            overflow: hidden;
        }}
        .leaflet-container {{ touch-action: manipulation; }}
        .map-container .map-label {{
            font-size: 12px; font-weight: 600; color: var(--slate);
            text-transform: uppercase; letter-spacing: 1px; padding: 12px 20px 0;
            display: flex; align-items: center; justify-content: space-between; gap: 12px;
        }}
        .map-label-right {{
            display: flex; align-items: center; gap: 12px;
        }}
        .map-coverage {{
            font-size: 11px; font-weight: 500; color: var(--slate);
            text-transform: none; letter-spacing: 0;
        }}
        .map-coverage-missing {{
            color: #b45309;
        }}
        .map-expand-btn {{
            font-family: inherit; font-size: 11px; font-weight: 600; color: var(--slate);
            background: #f5f0e8; border: 1px solid var(--light-border); border-radius: 6px;
            padding: 5px 10px; cursor: pointer; text-transform: none; letter-spacing: 0;
            transition: background 0.15s, color 0.15s;
        }}
        .map-expand-btn:hover {{
            background: var(--eucalyptus); color: #fff; border-color: var(--eucalyptus);
        }}
        .map-mobile-toggle {{ display: none; }}
        #shortlist-map {{ height: 480px; width: 100%; }}

        /* ── Map legend ─────────────────────────── */
        .map-legend {{
            display: flex; flex-wrap: wrap; align-items: center; gap: 14px;
            padding: 6px 20px 10px; font-size: 11px; color: var(--slate);
        }}
        .map-legend-item {{ display: inline-flex; align-items: center; gap: 5px; }}
        .map-legend-dot {{
            width: 10px; height: 10px; border-radius: 50%;
            border: 1.5px solid #fff; box-shadow: 0 0 0 0.5px rgba(0,0,0,0.15);
            display: inline-block;
        }}
        .map-legend-dot.fav {{ background: #fff; border-color: var(--fav-gold); box-shadow: 0 0 0 2px rgba(234,179,8,0.35); }}
        .map-legend-dot.syd {{ background: #ef4444; border-color: #fff; box-shadow: 0 0 0 0.5px rgba(0,0,0,0.15); }}

        /* ── Expanded map modal ─────────────────── */
        .map-modal {{
            position: fixed; inset: 0; background: rgba(15,23,42,0.85);
            z-index: 10000; display: flex; flex-direction: column;
            padding: 32px; box-sizing: border-box;
        }}
        .map-modal.hidden {{ display: none; }}
        .map-modal-header {{
            display: flex; align-items: center; justify-content: space-between;
            padding-bottom: 16px; color: #fff;
        }}
        .map-modal-title {{
            font-size: 14px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
        }}
        .map-modal-close {{
            background: transparent; border: 1px solid rgba(255,255,255,0.4); color: #fff;
            font-size: 14px; font-weight: 500; padding: 6px 14px; border-radius: 6px;
            cursor: pointer; font-family: inherit;
        }}
        .map-modal-close:hover {{
            background: rgba(255,255,255,0.12);
        }}
        #expanded-map {{
            flex: 1; width: 100%; border-radius: 10px; overflow: hidden;
            background: #fff;
        }}
        .map-pin {{
            display: flex; align-items: center; justify-content: center;
            width: 28px; height: 28px; border-radius: 50%;
            font-size: 12px; font-weight: 700; color: #fff;
            border: 2px solid #fff; box-shadow: 0 2px 6px rgba(0,0,0,0.25);
            cursor: pointer; transition: transform 0.2s;
        }}
        .property-cluster {{
            display: flex; align-items: center; justify-content: center;
            width: 38px; height: 38px; border-radius: 50%;
            background: var(--eucalyptus); color: #fff;
            border: 3px solid rgba(255,255,255,0.92);
            box-shadow: 0 2px 8px rgba(15,23,42,0.28);
            font-size: 12px; font-weight: 700;
        }}
        .map-pin.pulse {{
            animation: pinPulse 0.6s ease;
        }}
        @keyframes pinPulse {{
            0% {{ transform: scale(1); }}
            50% {{ transform: scale(1.5); }}
            100% {{ transform: scale(1); }}
        }}
        .map-pin.fav-pin {{ border-color: var(--fav-gold); box-shadow: 0 0 0 3px rgba(234,179,8,0.3), 0 2px 6px rgba(0,0,0,0.25); }}
        .leaflet-popup-content {{ font-family: Inter, sans-serif; font-size: 13px; line-height: 1.4; }}
        .popup-link {{
            color: var(--eucalyptus); font: inherit; font-weight: 600;
            text-decoration: none; cursor: pointer; background: none; border: 0;
            padding: 8px 0; min-height: 40px;
        }}

        /* ── Cards ───────────────────────────────── */
        .card {{
            background: #fff; border: 1px solid var(--light-border);
            border-radius: 10px; margin-bottom: 24px; overflow: hidden;
            transition: box-shadow 0.2s, opacity 0.4s, border-color 0.3s;
            content-visibility: auto; contain-intrinsic-size: auto 720px;
            scroll-margin-top: 64px;
        }}
        .card:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.06); }}
        .card.dismissed {{ opacity: 0.35; display: none; }}
        .card.dismissed.show-dismissed {{ display: block; }}
        .card.dismissed:hover {{ opacity: 0.6; }}
        .card.archived-card {{ display: none; border-color: #d6c7ad; }}
        .card.task-hidden {{ display: none !important; }}
        .availability-badge {{
            display: inline-block; padding: 3px 8px; border-radius: 4px;
            background: #fef3c7; color: #92400e; font-size: 10px;
            font-weight: 700; letter-spacing: 0.3px; text-transform: uppercase;
        }}
        html.past-view .card:not(.archived-card),
        html.past-view .summary,
        html.past-view .sort-bar,
        html.past-view .map-container,
        html.past-view .map-modal,
        html.past-view .dismissed-divider,
        html.past-view .view-empty {{ display: none; }}
        html.past-view .card.archived-card,
        html.past-view .past-summary {{ display: block; }}
        html.past-view .progress-bar {{ display: none !important; }}

        /* ── Dismissed section ─────────────────── */
        .dismissed-divider {{
            display: flex; align-items: center; justify-content: space-between;
            padding: 12px 20px; margin: 24px 0 12px;
            border-top: 1px solid var(--light-border);
        }}
        .dismissed-label {{
            font-size: 12px; font-weight: 600; color: var(--slate);
            text-transform: uppercase; letter-spacing: 0.5px;
        }}
        .dismissed-toggle {{
            font-family: Inter, -apple-system, sans-serif;
            font-size: 12px; font-weight: 500; padding: 4px 12px;
            border-radius: 16px; border: 1px solid var(--light-border);
            background: #fff; color: var(--slate); cursor: pointer;
        }}
        .dismissed-toggle:hover {{ border-color: var(--eucalyptus); color: var(--bark); }}
        .card.favourited {{ border-color: var(--fav-gold); border-width: 2px; }}

        .card-photo {{
            height: clamp(180px, 40vw, 240px); overflow: hidden;
            background: #e2e8f0;
        }}
        .card-photo img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
        .card-body {{ padding: 16px 20px 20px; }}

        .card-top-row {{
            display: flex; justify-content: space-between; align-items: flex-start;
            margin-bottom: 8px; gap: 8px;
        }}
        .card-header {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex: 1; }}
        .price {{ font-size: 20px; font-weight: 700; color: var(--bark); }}
        .score-badge {{
            font-size: 13px; font-weight: 600; padding: 3px 10px;
            border-radius: 14px; border: none; cursor: pointer;
            transition: box-shadow 0.15s;
        }}
        .score-badge:hover {{ box-shadow: 0 0 0 2px rgba(0,0,0,0.1); }}

        /* ── Favourite button ────────────────────── */
        .fav-btn {{
            background: none; border: none; cursor: pointer;
            width: 32px; height: 32px; padding: 4px;
            color: #d1d5db; transition: color 0.2s, transform 0.15s;
            flex-shrink: 0;
        }}
        .fav-btn:hover {{ color: #fbbf24; }}
        .fav-btn:active {{ transform: scale(1.2); }}
        .fav-btn svg {{ width: 100%; height: 100%; }}
        .fav-btn.active {{ color: var(--fav-gold); }}
        .fav-btn.active svg {{ fill: var(--fav-gold); }}

        /* ── Score breakdown ─────────────────────── */
        .breakdown {{
            background: #f8fafc; border-radius: 8px; padding: 12px 14px;
            margin-bottom: 10px;
        }}
        .bd-row {{
            display: flex; align-items: center; gap: 8px;
            margin-bottom: 4px; font-size: 12px;
        }}
        .bd-row:last-child {{ margin-bottom: 0; }}
        .bd-label {{ width: 90px; color: var(--slate); flex-shrink: 0; }}
        .bd-bar {{
            flex: 1; height: 6px; background: #e2e8f0;
            border-radius: 3px; overflow: hidden;
        }}
        .bd-fill {{ height: 100%; border-radius: 3px; transition: width 0.4s; }}
        .bd-val {{ width: 24px; text-align: right; font-weight: 600; color: var(--bark); }}

        .headline {{ font-size: 15px; font-weight: 600; color: #334155; margin-bottom: 4px; }}
        .address {{ font-size: 13px; color: var(--slate); margin-bottom: 10px; }}
        .stats {{
            font-size: 13px; color: #475569; margin-bottom: 12px;
            display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
        }}
        .stat-badge {{
            padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 500;
        }}
        .stat-stale {{
            font-size: 11px; color: var(--slate); opacity: 0.75;
            font-style: italic;
        }}
        .stat-fresh {{
            font-size: 11px; color: #475569;
            background: #f1f5f9; border: 1px solid #cbd5e1;
            padding: 1px 8px; border-radius: 10px;
            cursor: help;
        }}
        /* filter:opacity stacks with fadeUp animation (which holds opacity:1) */
        .card[data-stale="1"] {{ filter: opacity(0.78); transition: filter 0.2s; }}
        .card[data-stale="1"]:hover {{ filter: opacity(1); }}
        .description {{
            font-size: 13px; color: var(--slate); line-height: 1.6; margin-bottom: 12px;
        }}

        /* ── Tags ────────────────────────────────── */
        .tags {{ margin-bottom: 14px; display: flex; flex-wrap: wrap; gap: 4px; }}
        .tag {{
            background: #f1f5f9; color: #475569;
            padding: 2px 9px; border-radius: 10px; font-size: 11px;
        }}

        /* ── Buttons ─────────────────────────────── */
        .actions {{
            display: flex; flex-wrap: wrap; gap: 8px;
            align-items: center; margin-bottom: 8px;
        }}
        .feedback {{ display: flex; gap: 6px; flex-wrap: wrap; }}
        .btn {{
            display: inline-block; padding: 8px 16px; border-radius: 7px;
            text-decoration: none; font-size: 13px; font-weight: 500;
            border: none; cursor: pointer;
            transition: opacity 0.15s, transform 0.1s;
        }}
        .btn:active {{ transform: scale(0.97); }}
        .btn-view {{ background: var(--bark); color: #fff; }}
        .btn-love {{ background: #dcfce7; color: #166534; }}
        .btn-interesting {{ background: #dbeafe; color: #1e40af; }}
        .btn-pass {{ background: #f1f5f9; color: var(--slate); }}
        .btn-love.selected {{ background: #166534; color: #fff; }}
        .btn-interesting.selected {{ background: #1e40af; color: #fff; }}
        .btn-pass.selected {{ background: var(--slate); color: #fff; }}
        .btn:disabled {{ opacity: 0.5; cursor: default; }}

        /* ── Notes (shared, per-card) ────────────── */
        .notes-section {{ margin-top: 4px; }}
        .notes-pill {{
            font-size: 12px; background: none; border: none;
            cursor: pointer; padding: 4px 2px; font-family: inherit;
            color: var(--eucalyptus); font-weight: 500;
            transition: opacity 0.15s;
        }}
        .notes-pill.notes-pill-empty {{
            color: var(--slate); font-weight: 400; opacity: 0.6;
        }}
        .notes-pill.notes-pill-empty:hover {{ opacity: 1; }}
        .notes-pill.notes-pill-active {{
            background: rgba(76, 141, 86, 0.08);
            border-radius: 999px; padding: 3px 10px;
        }}
        .notes-drawer {{
            margin-top: 8px; padding: 10px 12px;
            background: #fafaf7; border: 1px solid var(--light-border);
            border-radius: 8px;
        }}
        .notes-list {{ display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; }}
        .notes-list:empty {{ display: none; }}
        .note {{
            padding: 8px 10px; background: #fff;
            border: 1px solid var(--light-border); border-radius: 7px;
        }}
        .note-meta {{
            font-size: 11px; color: var(--slate); margin-bottom: 3px;
            display: flex; gap: 8px; align-items: baseline;
        }}
        .note-author {{ font-weight: 600; color: var(--eucalyptus); text-transform: capitalize; }}
        .note-time {{ opacity: 0.7; }}
        .note-body {{
            font-size: 13px; color: var(--bark); line-height: 1.4;
            word-wrap: break-word;
        }}
        .notes-input-row {{ display: flex; gap: 6px; }}
        .notes-input {{
            flex: 1; border: 1px solid var(--light-border); border-radius: 7px;
            padding: 7px 10px; font-size: 13px; font-family: inherit;
            color: var(--bark); background: #fff;
        }}
        .notes-input:focus {{ outline: 2px solid var(--eucalyptus); border-color: transparent; }}
        .notes-post {{
            background: var(--eucalyptus); color: #fff; border: none;
            border-radius: 7px; padding: 7px 14px; font-size: 12px;
            font-weight: 500; cursor: pointer; font-family: inherit;
        }}
        .notes-post:hover {{ filter: brightness(1.08); }}
        .notes-post:disabled {{ opacity: 0.55; cursor: wait; }}

        /* ── Activity strip (page header) ────────── */
        .notes-activity {{
            font-size: 11px; padding: 0 20px; margin: -10px 0 14px;
        }}
        .notes-activity-toggle {{
            background: none; border: none; cursor: pointer;
            color: var(--eucalyptus); font-size: 11px; font-weight: 500;
            padding: 2px 0; font-family: inherit;
        }}
        .notes-activity-toggle:hover {{ text-decoration: underline; }}
        .notes-activity-panel {{
            margin-top: 8px; padding: 10px 12px;
            background: #fafaf7; border: 1px solid var(--light-border);
            border-radius: 8px; max-height: 280px; overflow-y: auto;
        }}
        .activity-item {{
            display: block; width: 100%; text-align: left; color: inherit;
            font: inherit;
            padding: 8px 10px; margin-bottom: 6px; background: #fff;
            border: 1px solid var(--light-border); border-radius: 7px;
            cursor: pointer; transition: border-color 0.15s;
        }}
        .activity-item:last-child {{ margin-bottom: 0; }}
        .activity-item:hover {{ border-color: var(--eucalyptus); }}
        .activity-meta {{
            font-size: 11px; color: var(--slate); margin-bottom: 3px;
        }}
        .activity-author {{ font-weight: 600; color: var(--eucalyptus); text-transform: capitalize; }}
        .activity-suburb {{ color: var(--bark); }}
        .activity-body {{ font-size: 12px; color: var(--bark); line-height: 1.4; }}

        /* ── Feedback identity ────────────────────── */
        .feedback-access {{
            margin: -4px 0 18px; display: flex; align-items: center;
            justify-content: flex-end; gap: 8px;
        }}
        .feedback-access[hidden] {{ display: none; }}
        .feedback-access label {{ font-size: 12px; color: var(--slate); font-weight: 600; }}
        .feedback-access-input {{
            min-width: 150px; max-width: 220px; padding: 8px 10px;
            border: 1px solid var(--light-border); border-radius: 7px;
            background: #fff; color: var(--bark); font: inherit; font-size: 12px;
        }}
        .identity-dialog {{
            width: min(420px, calc(100vw - 32px)); margin: auto;
            border: 0; border-radius: 12px; padding: 24px;
            background: #fff; color: var(--bark);
            box-shadow: 0 20px 60px rgba(15,23,42,0.28);
        }}
        .identity-dialog::backdrop {{ background: rgba(15,23,42,0.58); }}
        .identity-dialog h2 {{
            font-family: 'DM Serif Display', Georgia, serif;
            font-size: 24px; font-weight: 400; margin-bottom: 6px;
        }}
        .identity-dialog p {{ font-size: 13px; color: var(--slate); margin-bottom: 16px; }}
        .identity-choices {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
        .identity-choice {{
            min-height: 44px; border: 1px solid var(--light-border); border-radius: 8px;
            background: #fff; color: var(--bark); cursor: pointer; font: inherit;
            font-size: 13px; font-weight: 600;
        }}
        .identity-choice:hover {{ border-color: var(--eucalyptus); color: var(--eucalyptus); }}
        .identity-choice.anonymous {{ grid-column: 1 / -1; color: var(--slate); font-weight: 500; }}
        @media (max-width: 520px) {{
            .feedback-access {{ justify-content: space-between; }}
            .task-views button {{ padding-inline: 4px; }}
            .past-listings-link {{ align-items: flex-start; }}
            .map-container .map-label {{ padding: 12px 14px; }}
            .map-label-right {{ gap: 8px; }}
            .map-mobile-toggle {{
                display: inline-flex; align-items: center; justify-content: center;
                min-height: 40px; padding: 6px 10px; border-radius: 6px;
                border: 1px solid var(--eucalyptus); background: #fff;
                color: var(--eucalyptus); cursor: pointer; font: inherit;
                font-size: 11px; font-weight: 600;
            }}
            .map-container:not(.map-open) .map-legend,
            .map-container:not(.map-open) #shortlist-map,
            .map-container:not(.map-open) .map-desktop-action {{ display: none; }}
            .sort-bar {{ flex-wrap: wrap; overflow-x: visible; }}
            .sort-label {{ flex-basis: 100%; margin-bottom: 2px; }}
            .sort-btn {{ min-height: 44px; }}
            .task-views button, .past-listings-link, .map-expand-btn, .rank-badge, .score-badge,
            .fav-btn, .notes-post, .map-modal-close {{ min-height: 44px; }}
            .rank-badge {{ min-width: 44px; }}
            .fav-btn {{ width: 44px; height: 44px; padding: 6px; }}
            .feedback .btn, .notes-pill {{ min-height: 44px; }}
            body > nav > div {{
                padding-inline: 4px !important;
                scrollbar-width: auto !important;
            }}
            body > nav > div::-webkit-scrollbar {{ height: 3px; }}
            body > nav::after {{
                content: ''; position: absolute; top: 0; right: 0; bottom: 3px;
                width: 22px; pointer-events: none;
                background: linear-gradient(90deg, transparent, rgba(245,240,232,0.95));
            }}
        }}

        .feedback-confirmation {{
            font-size: 12px; color: var(--eucalyptus); font-weight: 500; padding: 4px 0;
        }}

        /* ── Progress bar (floating) ─────────────── */
        .progress-bar {{
            position: fixed; bottom: 0; left: 0; right: 0;
            background: rgba(255,255,255,0.95); backdrop-filter: blur(8px);
            border-top: 1px solid var(--light-border);
            padding: 10px 20px; z-index: 1000;
            display: flex; align-items: center; gap: 12px;
            justify-content: center;
            transition: opacity 0.3s;
        }}
        .progress-bar.hidden {{ opacity: 0; pointer-events: none; }}
        .progress-text {{ font-size: 13px; color: var(--slate); font-weight: 500; }}
        .progress-track {{
            width: 120px; height: 6px; background: #e2e8f0;
            border-radius: 3px; overflow: hidden;
        }}
        .progress-fill {{
            height: 100%; background: var(--eucalyptus);
            border-radius: 3px; transition: width 0.3s;
        }}
        .progress-favs {{
            font-size: 12px; color: var(--fav-gold); font-weight: 600;
        }}

        /* ── Footer ──────────────────────────────── */
        .footer {{
            text-align: center; padding: 28px 0 0;
            border-top: 1px solid var(--light-border); margin-top: 16px;
        }}
        .footer p {{ font-size: 12px; color: var(--slate); margin-bottom: 6px; }}

        /* ── Animations ──────────────────────────── */
        .card {{
            opacity: 0; transform: translateY(12px);
            animation: fadeUp 0.4s ease forwards;
        }}
        @keyframes fadeUp {{ to {{ opacity: 1; transform: translateY(0); }} }}
        .card:nth-child(1) {{ animation-delay: 0.05s; }}
        .card:nth-child(2) {{ animation-delay: 0.1s; }}
        .card:nth-child(3) {{ animation-delay: 0.15s; }}
        .card:nth-child(4) {{ animation-delay: 0.2s; }}
        .card:nth-child(5) {{ animation-delay: 0.25s; }}

        .card.dismissed {{ animation: none; }}

        @media (prefers-reduced-motion: reduce) {{
            .card {{ animation: none; opacity: 1; transform: none; }}
            .map-pin.pulse {{ animation: none; }}
        }}
    </style>
</head>
<body>
    <nav style="position:sticky;top:0;z-index:9999;background:rgba(245,240,232,0.92);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-bottom:1px solid #e2e8f0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
      <div style="max-width:640px;margin:0 auto;padding:0 16px;display:flex;gap:0;overflow-x:auto;scrollbar-width:none;">
        <a href="./" style="display:inline-flex;align-items:center;padding:14px 12px;font-size:13px;font-weight:600;color:#4A7C6B;text-decoration:none;white-space:nowrap;border-bottom:2px solid #4A7C6B;min-height:48px;">Shortlist</a>
        <a href="dashboard.html" style="display:inline-flex;align-items:center;padding:14px 12px;font-size:13px;font-weight:500;color:#64748b;text-decoration:none;white-space:nowrap;border-bottom:2px solid transparent;min-height:48px;">Area Insights</a>
        <a href="bolt-hole-overview.html" style="display:inline-flex;align-items:center;padding:14px 12px;font-size:13px;font-weight:500;color:#64748b;text-decoration:none;white-space:nowrap;border-bottom:2px solid transparent;min-height:48px;">About the Search</a>
      </div>
    </nav>
    <div class="container">

        <div class="header">
            <div class="brand">Bolt Hole Search</div>
            <h1>Bolt Hole &mdash; Property Shortlist</h1>
            <div class="freshness">Updated <span data-state="search-display">{_escape(search_date)}</span></div>
        </div>

        <div class="summary">
            <div class="count">{showing}</div>
            <div class="top">{top_match}</div>
        </div>

        <div class="task-views" aria-label="Shortlist view">
            <button type="button" data-view="review" aria-pressed="false" onclick="setTaskView('review')">To Review <span class="task-view-count" id="to-review-count">{total_found}</span></button>
            <button type="button" data-view="saved" aria-pressed="false" onclick="setTaskView('saved')">Saved <span class="task-view-count" id="saved-count">0</span></button>
            <button type="button" data-view="all" aria-pressed="false" onclick="setTaskView('all')">All Available <span class="task-view-count">{total_found}</span></button>
        </div>
        <a class="past-listings-link" href="?view=past">
            <span><strong>Past Listings</strong> &middot; {archived_count} no longer available</span>
            <span class="past-listings-arrow">View history &rarr;</span>
        </a>

        <div class="past-summary">
            <strong>{archived_count} past listings</strong>
            <span>No longer available. Previous notes and feedback are retained.</span>
        </div>

        <div class="feedback-access" id="feedback-access" hidden>
            <label for="feedback-name">Reviewing as</label>
            <select class="feedback-access-input" id="feedback-name" name="feedback-name" autocomplete="off" onchange="saveFeedbackName()">
                <option value="">Choose name…</option>
                <option value="George">George</option>
                <option value="Mary">Mary</option>
                <option value="Alex">Alex</option>
                <option value="Greg">Greg</option>
                <option value="Justin">Justin</option>
                <option value="__anonymous__">Anonymous — reactions stay on this device</option>
            </select>
        </div>
        <dialog class="identity-dialog" id="identity-dialog" aria-labelledby="identity-dialog-title">
            <h2 id="identity-dialog-title">Who's reviewing?</h2>
            <p>Choose your name to load your saved feedback on any device.</p>
            <div class="identity-choices">
                <button type="button" class="identity-choice" onclick="chooseFeedbackIdentity('George')">George</button>
                <button type="button" class="identity-choice" onclick="chooseFeedbackIdentity('Mary')">Mary</button>
                <button type="button" class="identity-choice" onclick="chooseFeedbackIdentity('Alex')">Alex</button>
                <button type="button" class="identity-choice" onclick="chooseFeedbackIdentity('Greg')">Greg</button>
                <button type="button" class="identity-choice" onclick="chooseFeedbackIdentity('Justin')">Justin</button>
                <button type="button" class="identity-choice anonymous" onclick="chooseFeedbackIdentity('')">Continue anonymously</button>
            </div>
            <p>Reactions and saved properties stay on this device. Notes are shared as Anonymous.</p>
        </dialog>
        <div class="notes-activity" id="notes-activity" style="display:none;">
            <button class="notes-activity-toggle" onclick="toggleActivity()">💬 <span id="notes-activity-count">0</span> recent notes</button>
            <div class="notes-activity-panel" id="notes-activity-panel" style="display:none;"></div>
        </div>

        <div class="sort-bar">
            <span class="sort-label">Sort by</span>
            <button class="sort-btn active" data-sort="score" onclick="sortCards('score')">Score</button>
            <button class="sort-btn" data-sort="price" onclick="sortCards('price')">Price</button>
            <button class="sort-btn" data-sort="ppa" onclick="sortCards('ppa')" title="Cheapest $/acre first">$/acre</button>
            <button class="sort-btn" data-sort="acres" onclick="sortCards('acres')">Acres</button>
            <button class="sort-btn" data-sort="drive" onclick="sortCards('drive')">Drive</button>
            <button class="sort-btn" data-sort="new" onclick="sortCards('new')">New ({new_count})</button>
        </div>

        <div class="map-container">
            <div class="map-label">
                <span>Where they are</span>
                <div class="map-label-right">
                    {map_coverage_badge}
                    <button type="button" class="map-expand-btn map-desktop-action" onclick="resetMapView()" title="Zoom out to show every property">&#x21BA; Reset</button>
                    <button type="button" class="map-expand-btn map-desktop-action" onclick="openExpandedMap()" title="Open full-screen map">Expand &nearr;</button>
                    <button type="button" class="map-mobile-toggle" aria-expanded="false" aria-controls="shortlist-map" onclick="toggleInlineMap()">View Map</button>
                </div>
            </div>
            <div class="map-legend" aria-label="Map pin colour legend">
                <span class="map-legend-item"><span class="map-legend-dot" style="background:#166534;"></span>70%+ match</span>
                <span class="map-legend-item"><span class="map-legend-dot" style="background:#1e40af;"></span>55&ndash;69%</span>
                <span class="map-legend-item"><span class="map-legend-dot" style="background:#92400e;"></span>40&ndash;54%</span>
                <span class="map-legend-item"><span class="map-legend-dot" style="background:#64748b;"></span>&lt;40%</span>
                <span class="map-legend-item"><span class="map-legend-dot fav"></span>Favourite</span>
                <span class="map-legend-item"><span class="map-legend-dot syd"></span>Sydney</span>
            </div>
            <div id="shortlist-map"></div>
        </div>

        <div class="map-modal hidden" id="map-modal" role="dialog" aria-modal="true" aria-label="Expanded shortlist map">
            <div class="map-modal-header">
                <div class="map-modal-title">All properties · map view</div>
                <button type="button" class="map-modal-close" onclick="closeExpandedMap()">Close &times;</button>
            </div>
            <div id="expanded-map"></div>
        </div>

        <div class="view-empty" id="view-empty" role="status"></div>

        {all_cards}

        <div class="footer">
            <p>Notes are shared. Select your name if you want reactions and favourites to follow you across devices.</p>
            <p>Prepared by Karl Howard &middot; Reforged</p>
        </div>

    </div>

    <!-- Progress bar -->
    <div class="progress-bar hidden" id="progress-bar">
        <span class="progress-text" id="progress-text">Reviewed 0 of {total_shown}</span>
        <div class="progress-track">
            <div class="progress-fill" id="progress-fill" style="width:0%"></div>
        </div>
        <span class="progress-favs" id="progress-favs"></span>
    </div>

    <script>
    function sortCards(by) {{
        const container = document.querySelector('.container');
        const cards = Array.from(container.querySelectorAll('.card:not(.archived-card)'));
        const sortFns = {{
            score: (a, b) => parseFloat(b.dataset.score) - parseFloat(a.dataset.score),
            price: (a, b) => {{
                const ap = parseFloat(a.dataset.price) || Infinity;
                const bp = parseFloat(b.dataset.price) || Infinity;
                return ap - bp;
            }},
            ppa: (a, b) => {{
                // Cheapest $/acre first; 0 sentinel (missing price or acres) pushed to end
                const ap = parseFloat(a.dataset.ppa) || Infinity;
                const bp = parseFloat(b.dataset.ppa) || Infinity;
                return ap - bp;
            }},
            acres: (a, b) => parseFloat(b.dataset.acres) - parseFloat(a.dataset.acres),
            drive: (a, b) => parseFloat(a.dataset.drive) - parseFloat(b.dataset.drive),
            new: (a, b) => {{
                const diff = parseInt(b.dataset.new) - parseInt(a.dataset.new);
                return diff !== 0 ? diff : parseFloat(b.dataset.score) - parseFloat(a.dataset.score);
            }},
        }};
        // Sort active cards, keep dismissed at the bottom
        const active = cards.filter(c => !c.classList.contains('dismissed'));
        const dismissed = cards.filter(c => c.classList.contains('dismissed'));
        active.sort(sortFns[by] || sortFns.score);
        const divider = document.getElementById('dismissed-divider');
        const footer = container.querySelector('.footer');
        const insertPoint = divider || footer;
        active.forEach(c => container.insertBefore(c, insertPoint));
        if (divider) dismissed.forEach(c => container.insertBefore(c, footer));
        document.querySelectorAll('.sort-btn').forEach(b => b.classList.toggle('active', b.dataset.sort === by));
    }}

    const NOTES_URL = "{notes_url_js}";
    const TOTAL = {total_shown};
    const state = {{
        feedback: {{}},
        favourites: {{}},
        anonymousNoteReviews: {{}},
        reviewed: 0,
        favCount: 0,
    }};
    const feedbackIdentity = {{ actorId: '', author: '', confirmed: false, version: 0 }};
    const KNOWN_FEEDBACK_NAMES = ['George', 'Mary', 'Alex', 'Greg', 'Justin'];
    const ACTOR_KEY = 'blh_feedback_actor_v1';
    const NAME_KEY = 'blh_feedback_name_v1';
    const IDENTITY_CONFIRMED_KEY = 'blh_feedback_identity_confirmed_v1';
    const ANONYMOUS_NOTE_REVIEW_KEY = 'blh_anonymous_note_reviews_v1';
    let identityPromptResolve = null;
    const requestedTaskView = new URLSearchParams(location.search).get('view');
    let currentTaskView = ['saved', 'all'].includes(requestedTaskView) ? requestedTaskView : 'review';

    function setTaskView(view) {{
        if (!['review', 'saved', 'all'].includes(view)) return;
        currentTaskView = view;
        document.documentElement.classList.remove('past-view');
        document.documentElement.classList.remove('task-view-review', 'task-view-saved', 'task-view-all');
        document.documentElement.classList.add('task-view-' + view);
        history.replaceState(null, '', view === 'review' ? location.pathname : '?view=' + view);
        applyTaskView();
        if (view === 'all') setTimeout(() => {{ if (map) map.invalidateSize(); }}, 0);
    }}

    function applyTaskView() {{
        if (document.documentElement.classList.contains('past-view')) return;
        const cards = Array.from(document.querySelectorAll('.card:not(.archived-card)'));
        let reviewCount = 0;
        let savedCount = 0;
        let visibleCount = 0;
        cards.forEach(card => {{
            const propertyId = card.dataset.propertyId;
            const reaction = state.feedback[propertyId] || '';
            const favourite = Boolean(state.favourites[propertyId]);
            const hasNamedNote = Boolean(feedbackIdentity.author)
                && (notesCache[propertyId] || []).some(note => note.author === feedbackIdentity.author);
            const hasAnonymousNote = !feedbackIdentity.author
                && feedbackIdentity.confirmed
                && Boolean(state.anonymousNoteReviews[propertyId]);
            const hasNote = hasNamedNote || hasAnonymousNote;
            const needsReview = !reaction && !favourite && !hasNote;
            const saved = favourite || reaction === 'love' || reaction === 'interesting';
            if (needsReview) reviewCount += 1;
            if (saved) savedCount += 1;
            const visible = currentTaskView === 'review'
                ? needsReview
                : currentTaskView === 'saved' ? saved : true;
            card.classList.toggle('task-hidden', !visible);
            if (visible && reaction !== 'pass') visibleCount += 1;
        }});
        const reviewCountEl = document.getElementById('to-review-count');
        const savedCountEl = document.getElementById('saved-count');
        if (reviewCountEl) reviewCountEl.textContent = String(reviewCount);
        if (savedCountEl) savedCountEl.textContent = String(savedCount);
        document.querySelectorAll('.task-views button[data-view]').forEach(button => {{
            button.setAttribute('aria-pressed', String(button.dataset.view === currentTaskView));
        }});
        const empty = document.getElementById('view-empty');
        if (empty) {{
            empty.style.display = visibleCount === 0 ? 'block' : 'none';
            empty.textContent = currentTaskView === 'review'
                ? 'Nothing left to review.'
                : currentTaskView === 'saved' ? 'No saved properties yet.' : '';
        }}
    }}

    function cardIdxForPid(pid) {{
        const card = document.querySelector('.card[data-property-id="' + CSS.escape(pid) + '"]');
        return card ? parseInt(card.dataset.idx) : null;
    }}

    function apiFetch(query, options = {{}}) {{
        const headers = new Headers(options.headers || {{}});
        if (options.body) headers.set('Content-Type', 'application/json');
        return fetch(NOTES_URL + query, {{...options, headers}});
    }}

    function identityPayload(extra = {{}}) {{
        return {{...extra, author: feedbackIdentity.author, actor_id: feedbackIdentity.actorId}};
    }}

    function identityQuery(action) {{
        const params = new URLSearchParams({{
            action,
            author: feedbackIdentity.author,
            actor_id: feedbackIdentity.actorId,
        }});
        return '?' + params.toString();
    }}

    function identityVersionIsCurrent(version) {{
        return version === feedbackIdentity.version;
    }}

    function clearPersonalUI() {{
        Object.entries(state.feedback).forEach(([pid]) => {{
            const idx = cardIdxForPid(pid);
            if (idx !== null) applyFeedbackUI(idx, null, false);
        }});
        Object.entries(state.favourites).forEach(([pid]) => {{
            const idx = cardIdxForPid(pid);
            if (idx !== null) removeFavouriteUI(idx);
        }});
        state.feedback = {{}};
        state.favourites = {{}};
        updateProgress();
        applyTaskView();
    }}

    async function saveFeedbackName(selectedValue = null) {{
        const input = document.getElementById('feedback-name');
        const selected = selectedValue === null ? (input?.value || '') : selectedValue;
        if (!KNOWN_FEEDBACK_NAMES.includes(selected) && selected !== '__anonymous__') return false;
        const author = KNOWN_FEEDBACK_NAMES.includes(selected) ? selected : '';
        feedbackIdentity.version += 1;
        const version = feedbackIdentity.version;
        clearPersonalUI();
        feedbackIdentity.author = author;
        feedbackIdentity.confirmed = true;
        if (author) localStorage.setItem(NAME_KEY, author);
        else localStorage.removeItem(NAME_KEY);
        localStorage.setItem(IDENTITY_CONFIRMED_KEY, '1');
        if (input) input.value = author || '__anonymous__';
        const access = document.getElementById('feedback-access');
        if (access) access.hidden = false;
        await Promise.allSettled([loadServerReactions(version), loadServerFavourites(version)]);
        return true;
    }}

    function ensureFeedbackIdentity() {{
        if (feedbackIdentity.confirmed) return Promise.resolve(true);
        const dialog = document.getElementById('identity-dialog');
        if (!dialog || typeof dialog.showModal !== 'function') return Promise.resolve(false);
        if (!dialog.open) dialog.showModal();
        return new Promise(resolve => {{ identityPromptResolve = resolve; }});
    }}

    async function chooseFeedbackIdentity(author) {{
        const selected = KNOWN_FEEDBACK_NAMES.includes(author) ? author : '__anonymous__';
        const saved = await saveFeedbackName(selected);
        const dialog = document.getElementById('identity-dialog');
        if (dialog?.open) dialog.close();
        if (identityPromptResolve) {{
            identityPromptResolve(saved);
            identityPromptResolve = null;
        }}
    }}

    async function initFeedbackIdentity() {{
        let actorId = localStorage.getItem(ACTOR_KEY) || '';
        if (!actorId) {{
            actorId = crypto.randomUUID();
            localStorage.setItem(ACTOR_KEY, actorId);
        }}
        feedbackIdentity.actorId = actorId;
        const storedName = localStorage.getItem(NAME_KEY) || '';
        feedbackIdentity.author = KNOWN_FEEDBACK_NAMES.includes(storedName) ? storedName : '';
        feedbackIdentity.confirmed = Boolean(feedbackIdentity.author)
            || localStorage.getItem(IDENTITY_CONFIRMED_KEY) === '1';
        feedbackIdentity.version += 1;
        const version = feedbackIdentity.version;
        if (storedName && !feedbackIdentity.author) localStorage.removeItem(NAME_KEY);
        const input = document.getElementById('feedback-name');
        if (input) input.value = feedbackIdentity.author || (feedbackIdentity.confirmed ? '__anonymous__' : '');
        const access = document.getElementById('feedback-access');
        if (access) access.hidden = !feedbackIdentity.confirmed;
        await Promise.allSettled([loadServerReactions(version), loadServerFavourites(version), loadNotes()]);
    }}

    async function loadServerReactions(version = feedbackIdentity.version) {{
        const response = await apiFetch(identityQuery('reactions'));
        if (!response.ok) throw new Error('Could not load reactions');
        const data = await response.json();
        if (!identityVersionIsCurrent(version)) return;
        const server = {{}};
        (data.reactions || []).forEach(r => {{
            if (r?.property_id && r?.reaction) server[r.property_id] = r.reaction;
        }});
        state.feedback = server;
        Object.entries(server).forEach(([pid, reaction]) => {{
            const idx = cardIdxForPid(pid);
            if (idx !== null) applyFeedbackUI(idx, reaction, false);
        }});
        state.reviewed = Object.keys(state.feedback).length;
        updateProgress();
        applyTaskView();
    }}

    // ── Feedback ──────────────────────────────────────────────────────
    async function sendFeedback(idx, propertyId, reaction) {{
        if (!await ensureFeedbackIdentity()) return;
        const version = feedbackIdentity.version;
        // Clicking an already-selected reaction clears it (neutral)
        const effective = state.feedback[propertyId] === reaction ? null : reaction;
        try {{
            const response = await apiFetch('', {{
                method: 'POST',
                body: JSON.stringify(identityPayload({{
                    action: 'reaction',
                    property_id: propertyId,
                    reaction: effective === null ? 'clear' : effective
                }}))
            }});
            if (!response.ok) throw new Error('Save rejected');
            if (!identityVersionIsCurrent(version)) return;
            if (effective === null) delete state.feedback[propertyId];
            else state.feedback[propertyId] = effective;
            state.reviewed = Object.keys(state.feedback).length;
            applyFeedbackUI(idx, effective, true);
            updateProgress();
            applyTaskView();
        }} catch {{
            if (identityVersionIsCurrent(version)) {{
                showConfirmation(idx, 'Could not save — please try again.');
            }}
        }}
    }}

    function applyFeedbackUI(idx, reaction, confirm = true) {{
        const card = document.getElementById('card-' + idx);
        const container = document.getElementById('feedback-' + idx);
        if (!container || !card) return;

        // Button highlighting — reaction of null clears all
        const buttons = container.querySelectorAll('button');
        buttons.forEach(btn => {{
            const selected = btn.dataset.reaction === reaction;
            btn.classList.toggle('selected', selected);
            btn.setAttribute('aria-pressed', String(selected));
        }});

        // Dismissed section membership only when reaction === 'pass'
        const wasDismissed = card.classList.contains('dismissed');
        const shouldDismiss = reaction === 'pass';
        card.classList.toggle('dismissed', shouldDismiss);

        if (shouldDismiss && !wasDismissed) {{
            moveToDismissed(card);
        }} else if (!shouldDismiss && wasDismissed) {{
            moveToActive(card);
        }}

        // Show confirmation
        const msg = reaction === 'love' ? 'Noted — love it!' :
                    reaction === 'interesting' ? 'Noted — worth a look.' :
                    reaction === 'pass' ? 'Noted — skipping this one.' :
                    'Cleared.';
        if (confirm) showConfirmation(idx, msg);

        // Update map pin
        updateMapPin(idx, reaction);
        updateDismissedCount();
    }}

    function moveToDismissed(card) {{
        const footer = document.querySelector('.footer');
        const divider = document.getElementById('dismissed-divider');
        if (divider) {{
            card.parentNode.insertBefore(card, divider);
        }} else if (footer) {{
            card.parentNode.insertBefore(card, footer);
        }}
    }}

    function moveToActive(card) {{
        // Move back above the dismissed divider, at the end of active cards
        const divider = document.getElementById('dismissed-divider');
        if (divider) {{
            card.parentNode.insertBefore(card, divider);
            // Re-sort: find the right position by score
            const container = card.parentNode;
            const activeCards = Array.from(container.querySelectorAll('.card:not(.dismissed):not(.archived-card)'));
            const myScore = parseFloat(card.dataset.score) || 0;
            const insertBefore = activeCards.find(c => c !== card && (parseFloat(c.dataset.score) || 0) < myScore);
            if (insertBefore) {{
                container.insertBefore(card, insertBefore);
            }}
        }}
    }}

    function updateDismissedCount() {{
        const dismissed = document.querySelectorAll('.card.dismissed:not(.archived-card)');
        const divider = document.getElementById('dismissed-divider');
        const count = dismissed.length;
        if (count > 0 && !divider) {{
            // Create dismissed section divider
            const d = document.createElement('div');
            d.id = 'dismissed-divider';
            d.className = 'dismissed-divider';
            d.innerHTML = '<span class="dismissed-label">Dismissed (' + count + ')</span>'
                + '<button class="dismissed-toggle" onclick="toggleDismissedVisibility()">Show</button>';
            const footer = document.querySelector('.footer');
            footer.parentNode.insertBefore(d, footer);
            // Move all dismissed cards below divider
            dismissed.forEach(c => d.parentNode.insertBefore(c, footer));
        }} else if (divider) {{
            const label = divider.querySelector('.dismissed-label');
            if (count > 0) {{
                label.textContent = 'Dismissed (' + count + ')';
            }} else {{
                divider.remove();
            }}
        }}
    }}

    function toggleDismissedVisibility() {{
        const dismissed = document.querySelectorAll('.card.dismissed:not(.archived-card)');
        const btn = document.querySelector('.dismissed-toggle');
        const showing = btn.textContent === 'Hide';
        dismissed.forEach(c => c.classList.toggle('show-dismissed', !showing));
        btn.textContent = showing ? 'Show' : 'Hide';
    }}

    // ── Favourites ────────────────────────────────────────────────────
    async function loadServerFavourites(version = feedbackIdentity.version) {{
        const response = await apiFetch(identityQuery('favourites'));
        if (!response.ok) throw new Error('Could not load favourites');
        const data = await response.json();
        if (!identityVersionIsCurrent(version)) return;
        const server = {{}};
        (data.favourites || []).forEach(favourite => {{
            if (favourite?.property_id) server[favourite.property_id] = true;
        }});
        state.favourites = server;
        Object.keys(server).forEach(pid => {{
            const idx = cardIdxForPid(pid);
            if (idx !== null) applyFavouriteUI(idx);
        }});
        state.favCount = Object.keys(server).length;
        updateProgress();
        applyTaskView();
    }}

    async function toggleFavourite(idx, propertyId) {{
        if (!await ensureFeedbackIdentity()) return;
        const version = feedbackIdentity.version;
        const isFav = !state.favourites[propertyId];
        try {{
            const response = await apiFetch('', {{
                method: 'POST',
                body: JSON.stringify(identityPayload({{
                    action: 'favourite',
                    property_id: propertyId,
                    favourite: isFav
                }}))
            }});
            if (!response.ok) throw new Error('Save rejected');
            if (!identityVersionIsCurrent(version)) return;
            if (isFav) {{
                state.favourites[propertyId] = true;
                applyFavouriteUI(idx);
            }} else {{
                delete state.favourites[propertyId];
                removeFavouriteUI(idx);
            }}
            state.favCount = Object.keys(state.favourites).length;
            updateProgress();
            applyTaskView();
            showConfirmation(idx, isFav ? 'Saved to your favourites.' : 'Removed from your favourites.');
        }} catch {{
            if (identityVersionIsCurrent(version)) {{
                showConfirmation(idx, 'Could not save — please try again.');
            }}
        }}
    }}

    function applyFavouriteUI(idx) {{
        const card = document.getElementById('card-' + idx);
        const btn = document.getElementById('fav-' + idx);
        if (card) card.classList.add('favourited');
        if (btn) {{
            btn.classList.add('active');
            btn.setAttribute('aria-pressed', 'true');
        }}
        // Update map pin
        const pinEl = document.querySelector('.map-pin[data-idx="' + idx + '"]');
        if (pinEl) pinEl.classList.add('fav-pin');
    }}

    function removeFavouriteUI(idx) {{
        const card = document.getElementById('card-' + idx);
        const btn = document.getElementById('fav-' + idx);
        if (card) card.classList.remove('favourited');
        if (btn) {{
            btn.classList.remove('active');
            btn.setAttribute('aria-pressed', 'false');
        }}
        const pinEl = document.querySelector('.map-pin[data-idx="' + idx + '"]');
        if (pinEl) pinEl.classList.remove('fav-pin');
    }}

    // ── Score breakdown toggle ────────────────────────────────────────
    function toggleBreakdown(idx) {{
        const el = document.getElementById('breakdown-' + idx);
        const btn = document.getElementById('score-' + idx);
        if (!el) return;
        const open = el.style.display === 'none';
        el.style.display = open ? 'block' : 'none';
        if (btn) btn.setAttribute('aria-expanded', String(open));
    }}

    // ── Attributed shared notes ───────────────────────────────────────
    let notesCache = {{}};
    const pendingNoteSaves = {{}};

    function loadAnonymousNoteReviews() {{
        try {{
            const stored = JSON.parse(localStorage.getItem(ANONYMOUS_NOTE_REVIEW_KEY) || '{{}}');
            state.anonymousNoteReviews = stored && typeof stored === 'object' ? stored : {{}};
        }} catch {{
            state.anonymousNoteReviews = {{}};
        }}
    }}

    function rememberAnonymousNoteReview(propertyId) {{
        state.anonymousNoteReviews[propertyId] = true;
        localStorage.setItem(ANONYMOUS_NOTE_REVIEW_KEY, JSON.stringify(state.anonymousNoteReviews));
    }}

    function escapeHtml(s) {{
        return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);
    }}

    function formatNoteDate(iso) {{
        const d = new Date(iso);
        if (isNaN(d)) return '';
        const diff = (Date.now() - d.getTime()) / 1000;
        if (diff < 60) return 'just now';
        if (diff < 3600) return Math.floor(diff/60) + 'm ago';
        if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
        if (diff < 86400*7) return Math.floor(diff/86400) + 'd ago';
        return d.toLocaleDateString(undefined, {{month:'short', day:'numeric'}});
    }}

    async function loadNotes() {{
        const response = await apiFetch('');
        if (!response.ok) throw new Error('Could not load notes');
        const data = await response.json();
        const next = {{}};
        (data.notes || []).forEach(n => {{
            (next[n.property_id] = next[n.property_id] || []).push(n);
        }});
        notesCache = next;
        Object.values(notesCache).forEach(list =>
            list.sort((a,b) => new Date(a.timestamp) - new Date(b.timestamp)));
        document.querySelectorAll('.notes-section').forEach(section => {{
            const pid = section.dataset.propertyId;
            const idx = section.id.replace('notes-section-', '');
            renderNotesIntoCard(idx, notesCache[pid] || []);
        }});
        updateActivityStrip(data.notes || []);
        applyTaskView();
    }}

    function renderNotesIntoCard(idx, notes) {{
        const pill = document.querySelector('#notes-section-' + idx + ' .notes-pill');
        const list = document.getElementById('notes-list-' + idx);
        if (!pill || !list) return;
        if (!notes.length) {{
            pill.textContent = '+ note';
            pill.classList.add('notes-pill-empty');
            pill.classList.remove('notes-pill-active');
            list.innerHTML = '';
            return;
        }}
        pill.innerHTML = '💬 ' + notes.length + (notes.length === 1 ? ' note' : ' notes');
        pill.classList.remove('notes-pill-empty');
        pill.classList.add('notes-pill-active');
        list.innerHTML = notes.map(n => (
            '<div class="note"><div class="note-meta">' +
                '<span class="note-author">' + escapeHtml(n.author || 'Unknown') + '</span> · ' +
                '<span class="note-time">' + escapeHtml(formatNoteDate(n.timestamp)) + '</span>' +
            '</div><div class="note-body">' + escapeHtml(n.note) + '</div></div>'
        )).join('');
    }}

    function toggleNotes(idx) {{
        const drawer = document.getElementById('notes-drawer-' + idx);
        if (!drawer) return;
        const isOpen = drawer.style.display === 'block';
        drawer.style.display = isOpen ? 'none' : 'block';
        const pill = document.querySelector('#notes-section-' + idx + ' .notes-pill');
        if (pill) pill.setAttribute('aria-expanded', String(!isOpen));
        if (!isOpen) {{
            const input = document.getElementById('notes-input-' + idx);
            if (input) input.focus();
        }}
    }}

    async function submitNote(idx, propertyId) {{
        if (pendingNoteSaves[propertyId]) return;
        const input = document.getElementById('notes-input-' + idx);
        const button = document.getElementById('notes-post-' + idx);
        if (!input) return;
        const text = (input.value || '').trim();
        if (!text || !NOTES_URL) return;
        if (!await ensureFeedbackIdentity()) return;
        pendingNoteSaves[propertyId] = true;
        input.disabled = true;
        if (button) button.disabled = true;
        const body = JSON.stringify(identityPayload({{
            action: 'note',
            property_id: propertyId,
            idempotency_key: crypto.randomUUID(),
            note: text
        }}));
        const postOnce = async () => {{
            const response = await apiFetch('', {{method: 'POST', body}});
            if (!response.ok) throw new Error('Save rejected');
            return response.json();
        }};
        try {{
            let data;
            try {{ data = await postOnce(); }}
            catch {{ data = await postOnce(); }}
            if (!data.note) throw new Error('Missing saved note');
            (notesCache[propertyId] = notesCache[propertyId] || []).push(data.note);
            notesCache[propertyId].sort((a,b) => new Date(a.timestamp) - new Date(b.timestamp));
            if (!feedbackIdentity.author) rememberAnonymousNoteReview(propertyId);
            renderNotesIntoCard(idx, notesCache[propertyId]);
            input.value = '';
            updateActivityStrip(Object.values(notesCache).flat());
            applyTaskView();
            showConfirmation(idx, 'Saved as ' + data.note.author + '.');
        }} catch {{
            showConfirmation(idx, 'Could not save — your note is still here.');
        }} finally {{
            delete pendingNoteSaves[propertyId];
            input.disabled = false;
            if (button) button.disabled = false;
        }}
    }}

    function noteKeydown(event, idx, propertyId) {{
        if (event.key === 'Enter' && !event.shiftKey) {{
            event.preventDefault();
            submitNote(idx, propertyId);
        }}
    }}

    function updateActivityStrip(allNotes) {{
        const wrap = document.getElementById('notes-activity');
        const countEl = document.getElementById('notes-activity-count');
        const panel = document.getElementById('notes-activity-panel');
        if (!wrap || !countEl || !panel) return;
        if (!allNotes.length) {{ wrap.style.display = 'none'; return; }}
        wrap.style.display = '';
        countEl.textContent = allNotes.length;
        const sorted = allNotes.slice().sort((a,b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 10);
        panel.innerHTML = sorted.map(n => {{
            const section = document.querySelector('.notes-section[data-property-id="' + n.property_id + '"]');
            const card = section ? section.closest('.card') : null;
            const addr = card ? (card.querySelector('.address')?.textContent || '').split(',')[0].trim() : n.property_id;
            const pidAttr = escapeHtml(n.property_id);
            return '<button type="button" class="activity-item" onclick="scrollToProperty(\\'' + pidAttr.replace(/'/g, "\\\\'") + '\\')">' +
                '<div class="activity-meta">' +
                    '<span class="activity-author">' + escapeHtml(n.author || 'Unknown') + '</span> · ' +
                    '<span class="activity-suburb">' + escapeHtml(addr || '—') + '</span> · ' +
                    '<span class="note-time">' + escapeHtml(formatNoteDate(n.timestamp)) + '</span>' +
                '</div><div class="activity-body">' + escapeHtml(n.note) + '</div></button>';
        }}).join('');
    }}

    function toggleActivity() {{
        const panel = document.getElementById('notes-activity-panel');
        if (!panel) return;
        panel.style.display = panel.style.display === 'block' ? 'none' : 'block';
    }}

    function scrollToProperty(pid) {{
        const section = document.querySelector('.notes-section[data-property-id="' + pid + '"]');
        if (!section) return;
        const card = section.closest('.card');
        if (!card) return;
        if (card.classList.contains('archived-card')) {{
            document.documentElement.classList.add('past-view');
            history.replaceState(null, '', '?view=past');
        }}
        card.scrollIntoView({{behavior:'smooth', block:'start'}});
        const idx = section.id.replace('notes-section-', '');
        const drawer = document.getElementById('notes-drawer-' + idx);
        if (drawer && drawer.style.display !== 'block') toggleNotes(idx);
        const panel = document.getElementById('notes-activity-panel');
        if (panel) panel.style.display = 'none';
    }}

    function showConfirmation(idx, message) {{
        const el = document.getElementById('confirm-' + idx);
        if (!el) return;
        el.textContent = message;
        el.style.display = 'block';
        setTimeout(() => {{ el.style.display = 'none'; }}, 3000);
    }}

    // ── Progress bar ──────────────────────────────────────────────────
    function updateProgress() {{
        const bar = document.getElementById('progress-bar');
        const text = document.getElementById('progress-text');
        const fill = document.getElementById('progress-fill');
        const favs = document.getElementById('progress-favs');

        const reviewed = Object.keys(state.feedback).length;
        const favCount = Object.values(state.favourites).filter(Boolean).length;

        if (reviewed === 0 && favCount === 0) {{
            bar.classList.add('hidden');
            return;
        }}

        bar.classList.remove('hidden');
        text.textContent = 'Reviewed ' + reviewed + ' of ' + TOTAL;
        fill.style.width = (reviewed / TOTAL * 100) + '%';
        favs.textContent = favCount > 0 ? favCount + ' fav' + (favCount > 1 ? 's' : '') : '';
    }}

    // ── Map ───────────────────────────────────────────────────────────
    const markersData = {markers_json};
    const mapPinEls = {{}};   // idx -> DOM element of the pin div
    const mapMarkers = {{}};  // idx -> Leaflet marker

    function pinColor(pct) {{
        if (pct >= 70) return '#166534';
        if (pct >= 55) return '#1e40af';
        if (pct >= 40) return '#92400e';
        return '#64748b';
    }}

    function createPropertyClusterGroup() {{
        const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        return L.markerClusterGroup({{
            maxClusterRadius: 44,
            disableClusteringAtZoom: 11,
            showCoverageOnHover: false,
            spiderfyOnMaxZoom: true,
            chunkedLoading: true,
            animate: !reducedMotion,
            iconCreateFunction(cluster) {{
                const count = cluster.getChildCount();
                return L.divIcon({{
                    className: '',
                    html: '<div class="property-cluster" aria-label="' + count + ' nearby properties">' + count + '</div>',
                    iconSize: [38, 38],
                    iconAnchor: [19, 19]
                }});
            }}
        }});
    }}

    function wireMarkerAccessibility(marker, m) {{
        const decorate = () => {{
            const el = marker.getElement();
            if (!el) return;
            el.setAttribute('aria-label', 'Property ' + (m.idx + 1) + ' in ' + m.suburb + '. Open map details.');
            if (el.dataset.keyboardWired === '1') return;
            el.dataset.keyboardWired = '1';
            el.addEventListener('keydown', event => {{
                if (event.key !== 'Enter' && event.key !== ' ') return;
                event.preventDefault();
                marker.openPopup();
            }});
        }};
        decorate();
        marker.on('add', decorate);
    }}

    function scrollToCard(idx) {{
        const card = document.getElementById('card-' + idx);
        if (!card) return;
        const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        card.style.contentVisibility = 'visible';
        let attempts = 0;

        function alignCard() {{
            const behavior = reducedMotion || attempts === 0 ? 'auto' : 'smooth';
            card.scrollIntoView({{ behavior, block: 'start' }});
            attempts += 1;
            window.setTimeout(() => {{
                const stickyOffset = 64;
                const distance = Math.abs(card.getBoundingClientRect().top - stickyOffset);
                if (distance > 16 && attempts < 4) {{
                    alignCard();
                    return;
                }}
                const focusTarget = card.querySelector('button, a');
                if (focusTarget) focusTarget.focus({{ preventScroll: true }});
                card.style.removeProperty('content-visibility');
            }}, reducedMotion ? 0 : 180);
        }}

        window.requestAnimationFrame(alignCard);
    }}

    function pulsePin(idx) {{
        const pin = mapPinEls[idx];
        if (!pin) return;
        pin.classList.remove('pulse');
        void pin.offsetWidth; // reflow to restart animation
        pin.classList.add('pulse');
    }}

    let initialMapBounds = null;

    function panMapToCard(idx) {{
        const marker = mapMarkers[idx];
        if (!marker || !map) return;
        const mapEl = document.getElementById('shortlist-map');
        const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (mapEl) mapEl.scrollIntoView({{ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center' }});
        // Defer pan/zoom until the smooth-scroll has settled so the popup
        // anchors correctly relative to the now-visible map viewport.
        setTimeout(() => {{
            const revealMarker = () => {{
                marker.openPopup();
                pulsePin(idx);
            }};
            if (propertyClusters) {{
                propertyClusters.zoomToShowLayer(marker, revealMarker);
            }} else {{
                map.setView(marker.getLatLng(), Math.max(map.getZoom(), 11), {{ animate: !reducedMotion }});
                revealMarker();
            }}
        }}, 350);
    }}

    function resetMapView() {{
        if (!map || !initialMapBounds) return;
        map.closePopup();
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {{
            map.fitBounds(initialMapBounds, {{ padding: [30, 30], animate: false }});
        }} else {{
            map.flyToBounds(initialMapBounds, {{ padding: [30, 30], duration: 0.6 }});
        }}
    }}

    function toggleInlineMap() {{
        const container = document.querySelector('.map-container');
        const button = document.querySelector('.map-mobile-toggle');
        if (!container || !button) return;
        const open = container.classList.toggle('map-open');
        button.setAttribute('aria-expanded', String(open));
        button.textContent = open ? 'Hide Map' : 'View Map';
        if (open) setTimeout(() => {{ if (map) map.invalidateSize(); }}, 0);
    }}

    function updateMapPin(idx, reaction) {{
        const marker = mapMarkers[idx];
        const pin = mapPinEls[idx];
        if (reaction === 'pass') {{
            // Remove from map entirely
            if (marker && propertyClusters) propertyClusters.removeLayer(marker);
        }} else {{
            // Add back if was removed
            if (marker && propertyClusters && !propertyClusters.hasLayer(marker)) propertyClusters.addLayer(marker);
            if (pin) {{
                if (reaction === 'love') {{
                    pin.style.background = '#166534';
                }} else {{
                    // Neutral or interesting — restore default pin colour
                    pin.style.background = '';
                }}
                pin.style.opacity = '1';
            }}
        }}
    }}

    function restoreMapPinState(idx, pct, pin) {{
        const card = document.getElementById('card-' + idx);
        const propertyId = card?.dataset.propertyId;
        if (!pin || !propertyId) return;
        pin.classList.toggle('fav-pin', Boolean(state.favourites[propertyId]));
        pin.style.background = state.feedback[propertyId] === 'love'
            ? '#166534'
            : pinColor(pct);
        pin.style.opacity = '1';
    }}

    let map;
    let propertyClusters;
    if (markersData.length > 0) {{
        map = L.map('shortlist-map', {{ zoomControl: true, attributionControl: false }});
        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}@2x.png', {{
            maxZoom: 14,
            attribution: '&copy; OSM &amp; CARTO'
        }}).addTo(map);

        // Sydney marker
        L.circleMarker([-33.8688, 151.2653], {{
            radius: 5, fillColor: '#ef4444', fillOpacity: 0.9,
            color: '#fff', weight: 2
        }}).addTo(map).bindPopup('<strong>Sydney</strong><br>Reference point');

        const bounds = [[-33.8688, 151.2653]];
        propertyClusters = createPropertyClusterGroup().addTo(map);

        markersData.forEach(m => {{
            const color = pinColor(m.pct);
            const icon = L.divIcon({{
                className: '',
                html: '<div class="map-pin" data-idx="' + m.idx + '" style="background:' + color + ';">' + (m.idx + 1) + '</div>',
                iconSize: [28, 28],
                iconAnchor: [14, 14],
                popupAnchor: [0, -16]
            }});

            const marker = L.marker([m.lat, m.lng], {{ icon: icon }});
            marker.bindPopup(
                '<strong>' + m.suburb + '</strong><br>' +
                m.price + (m.acres ? ' &middot; ' + m.acres : '') +
                ' &middot; ' + m.pct.toFixed(0) + '%<br>' +
                '<button type="button" class="popup-link" onclick="scrollToCard(' + m.idx + ')">Jump to card &darr;</button>'
            );
            wireMarkerAccessibility(marker, m);
            propertyClusters.addLayer(marker);

            mapMarkers[m.idx] = marker;
            bounds.push([m.lat, m.lng]);

            // Grab pin DOM reference after it renders
            marker.on('add', () => {{
                setTimeout(() => {{
                    const el = document.querySelector('.map-pin[data-idx="' + m.idx + '"]');
                    if (el) {{
                        mapPinEls[m.idx] = el;
                        restoreMapPinState(m.idx, m.pct, el);
                    }}
                }}, 50);
            }});
        }});

        map.fitBounds(bounds, {{ padding: [30, 30] }});
        initialMapBounds = bounds;
    }} else {{
        document.querySelector('.map-container').style.display = 'none';
    }}

    // ── Scroll observer: pulse map pin when card enters viewport ──────
    if (typeof IntersectionObserver !== 'undefined') {{
        const observer = new IntersectionObserver(entries => {{
            entries.forEach(entry => {{
                if (entry.isIntersecting) {{
                    const idx = parseInt(entry.target.dataset.idx);
                    if (!isNaN(idx)) pulsePin(idx);
                }}
            }});
        }}, {{ threshold: 0.5 }});

        document.querySelectorAll('.card[data-idx]').forEach(card => {{
            observer.observe(card);
        }});
    }}

    // ── Expanded-map modal ───────────────────────────────────────────
    let expandedMap = null;
    let expandedMapTrigger = null;
    function openExpandedMap() {{
        const modal = document.getElementById('map-modal');
        if (!modal) return;
        expandedMapTrigger = document.activeElement;
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        const closeButton = modal.querySelector('.map-modal-close');
        if (closeButton) closeButton.focus();
        if (!expandedMap && typeof markersData !== 'undefined' && markersData.length > 0) {{
            expandedMap = L.map('expanded-map', {{ zoomControl: true, attributionControl: false }});
            L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}@2x.png', {{
                maxZoom: 14, attribution: '&copy; OSM &amp; CARTO'
            }}).addTo(expandedMap);
            L.circleMarker([-33.8688, 151.2653], {{
                radius: 5, fillColor: '#ef4444', fillOpacity: 0.9, color: '#fff', weight: 2
            }}).addTo(expandedMap).bindPopup('<strong>Sydney</strong><br>Reference point');
            const eb = [[-33.8688, 151.2653]];
            const expandedClusters = createPropertyClusterGroup().addTo(expandedMap);
            markersData.forEach(m => {{
                const color = pinColor(m.pct);
                const icon = L.divIcon({{
                    className: '',
                    html: '<div class="map-pin" style="background:' + color + ';">' + (m.idx + 1) + '</div>',
                    iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -16]
                }});
                const marker = L.marker([m.lat, m.lng], {{ icon: icon }});
                marker.bindPopup(
                    '<strong>' + m.suburb + '</strong><br>' +
                    m.price + (m.acres ? ' &middot; ' + m.acres : '') +
                    ' &middot; ' + m.pct.toFixed(0) + '%<br>' +
                    '<button type="button" class="popup-link" onclick="closeExpandedMap(); scrollToCard(' + m.idx + ')">Jump to card &darr;</button>'
                );
                wireMarkerAccessibility(marker, m);
                expandedClusters.addLayer(marker);
                eb.push([m.lat, m.lng]);
            }});
            expandedMap.fitBounds(eb, {{ padding: [40, 40] }});
        }}
        setTimeout(() => {{ if (expandedMap) expandedMap.invalidateSize(); }}, 50);
    }}
    function closeExpandedMap() {{
        const modal = document.getElementById('map-modal');
        if (!modal) return;
        modal.classList.add('hidden');
        document.body.style.overflow = '';
        if (expandedMapTrigger && typeof expandedMapTrigger.focus === 'function') expandedMapTrigger.focus();
        expandedMapTrigger = null;
    }}
    (function wireExpandedMap() {{
        const modal = document.getElementById('map-modal');
        if (!modal) return;
        modal.addEventListener('click', e => {{ if (e.target === modal) closeExpandedMap(); }});
        document.addEventListener('keydown', e => {{
            if (e.key === 'Escape' && !modal.classList.contains('hidden')) closeExpandedMap();
            if (e.key !== 'Tab' || modal.classList.contains('hidden')) return;
            const focusable = Array.from(modal.querySelectorAll('button, [href], [tabindex]:not([tabindex="-1"])'))
                .filter(el => !el.disabled && el.offsetParent !== null);
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey && document.activeElement === first) {{
                e.preventDefault();
                last.focus();
            }} else if (!e.shiftKey && document.activeElement === last) {{
                e.preventDefault();
                first.focus();
            }}
        }});
    }})();

    document.getElementById('identity-dialog')?.addEventListener('cancel', () => {{
        if (identityPromptResolve) {{
            identityPromptResolve(false);
            identityPromptResolve = null;
        }}
    }});

    // ── Restore the optional feedback name and this browser's identity ─
    loadAnonymousNoteReviews();
    applyTaskView();
    initFeedbackIdentity();
    </script>
</body>
</html>'''

    page_html = "\n".join(line.rstrip() for line in page_html.splitlines()) + "\n"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=output_path.parent, prefix=f".{output_path.name}.", delete=False
    ) as f:
        f.write(page_html)
        f.flush()
        os.fsync(f.fileno())
        temp_path = Path(f.name)
    temp_path.replace(output_path)

    print(f"Shortlist: {len(props)} properties -> {output_path}")
    return output_path


# ── CLI ───────────────────────────────────────────────────────────────────

def _parse_run_timestamp(filename_stem):
    """search_20260423_1339 → datetime; None on parse failure."""
    parts = filename_stem.split("_")
    if len(parts) != 3:
        return None
    try:
        return datetime.strptime(f"{parts[1]}_{parts[2]}", "%Y%m%d_%H%M")
    except ValueError:
        return None


def _fetch_sheet_properties():
    """
    Fetch properties from the D1-backed API keyed by source_id. Returns {} if
    the endpoint is absent or unavailable. Never raises — the remote database
    supplements the local JSON snapshots during rendering.
    """
    url = os.getenv(
        "NOTES_SCRIPT_URL",
        "https://bolt-hole-backend.karl-582.workers.dev",
    )
    if not url:
        return {}
    import urllib.request
    import urllib.error
    try:
        request = urllib.request.Request(
            url + "?action=properties",
            headers={"User-Agent": "bolt-hole-shortlist/1.0"},
        )
        with urllib.request.urlopen(request, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        return {}
    out = {}
    for row in data.get("properties", []):
        sid = row.get("source_id")
        if not sid:
            continue
        out[str(sid)] = row
    return out


def _parse_iso_datetime(value):
    """Parse ISO-ish timestamps from source payloads; return naive datetime or None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return dt
    except (TypeError, ValueError):
        return None


def _is_realestate_com_listing(prop):
    """True only for realestate.com.au listings, not Elders/CommercialRealEstate."""
    source = (prop.get("source") or "").lower()
    url = prop.get("listing_url") or ""
    host = urlparse(url).netloc.lower()
    return source in {"rea_apify", "rea_web", "rea"} or host == "realestate.com.au" or host.endswith(".realestate.com.au")


def _union_source_files(results_files, latest_ts, age_out_days, min_runs):
    """Return newest files worth unioning.

    The old implementation used only the latest N result files. That is brittle
    when a source has several same-day failed/partial runs: useful listings can
    be pushed out of the N-file window long before they are actually stale.
    Use the whole retention horizon instead, while still keeping at least N
    files for sparse histories.
    """
    cutoff = latest_ts - timedelta(days=age_out_days)
    selected = []
    for fp in results_files:
        run_ts = _parse_run_timestamp(fp.stem)
        if len(selected) < min_runs or (run_ts and run_ts >= cutoff):
            selected.append(fp)
    return selected


def _load_union_of_runs(runs_to_union=3, age_out_days=21, rea_new_days=9):
    """
    Union properties across recent scrape JSONs by source_id, then overlay any
    sheet-only properties still within the age-out window. Local JSON data wins
    when present (freshest). Properties missing from the latest run get
    'missing_from_latest' + 'last_seen_days' so the UI can mark them stale.

    Important source-failure rule: scan the full age-out horizon, not just the
    latest N files. Temporary source failures can otherwise evict recent
    realestate.com.au listings after a handful of bad runs. Any realestate.com.au
    listing with date_listed in the last `rea_new_days` is explicitly retained.
    Returns (props_list, latest_file).
    """
    results_files = sorted(RESULTS_DIR.glob("search_*.json"), reverse=True)
    if not results_files:
        return [], None

    latest_file = results_files[0]
    latest_ts = _parse_run_timestamp(latest_file.stem) or datetime.now()
    latest_ids = set()
    union = {}  # source_id -> {"prop": dict, "last_seen": datetime, "first_seen": datetime}

    # Iterate newest-first so newer data wins, but include the whole retention
    # horizon so repeated failed/partial runs cannot push live-but-unrefreshed
    # listings out of the published list prematurely.
    for fp in _union_source_files(results_files, latest_ts, age_out_days, runs_to_union):
        run_ts = _parse_run_timestamp(fp.stem)
        try:
            with open(fp) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue
        for p in data.get("properties", []):
            sid = p.get("source_id") or p.get("id")
            if not sid:
                continue
            if fp == latest_file:
                latest_ids.add(sid)
            if sid not in union:
                ts = run_ts or latest_ts
                union[sid] = {"prop": p, "last_seen": ts, "first_seen": ts}
            elif run_ts and run_ts < union[sid]["first_seen"]:
                # Walking newest-first: subsequent occurrences are older, so
                # extend first_seen backwards as far as our scrape window goes.
                union[sid]["first_seen"] = run_ts

    # Sheet overlay — fills gaps for properties not present in local JSONs but
    # recorded in the sheet (e.g. other machines, or runs deleted from disk).
    now = datetime.now()
    sheet_props = _fetch_sheet_properties()
    sheet_added = 0
    for sid, row in sheet_props.items():
        if sid in union:
            continue
        payload = row.get("payload")
        if isinstance(payload, dict) and payload:
            prop = dict(payload)
        else:
            continue
        prop["status"] = row.get("status") or prop.get("status") or "active"
        # Age-out using last_seen from sheet
        last_seen_iso = row.get("last_seen")
        if last_seen_iso:
            try:
                last_seen = datetime.fromisoformat(str(last_seen_iso).replace("Z", "+00:00"))
                if last_seen.tzinfo:
                    last_seen = last_seen.replace(tzinfo=None)
            except ValueError:
                last_seen = now
        else:
            last_seen = now
        first_seen_iso = row.get("first_seen")
        if first_seen_iso:
            try:
                first_seen_dt = datetime.fromisoformat(str(first_seen_iso).replace("Z", "+00:00"))
                if first_seen_dt.tzinfo:
                    first_seen_dt = first_seen_dt.replace(tzinfo=None)
            except ValueError:
                first_seen_dt = last_seen
        else:
            first_seen_dt = last_seen
        union[sid] = {"prop": prop, "last_seen": last_seen, "first_seen": first_seen_dt}
        sheet_added += 1
    if sheet_added:
        print(f"Sheet overlay: +{sheet_added} properties not in local runs")

    # The database may know an older first_seen or a human-set terminal status.
    # Only sold/withdrawn are treated as manual overrides when a listing appears
    # in the latest scrape; transient archive warnings reactivate automatically.
    for sid, record in union.items():
        sheet_row = sheet_props.get(sid)
        if not sheet_row:
            continue
        if sheet_row.get("first_seen"):
            try:
                sheet_first = datetime.fromisoformat(
                    str(sheet_row["first_seen"]).replace("Z", "+00:00"))
                if sheet_first.tzinfo:
                    sheet_first = sheet_first.replace(tzinfo=None)
                if sheet_first < record["first_seen"]:
                    record["first_seen"] = sheet_first
            except ValueError:
                pass
        if sheet_row.get("status") in ("sold", "withdrawn"):
            record["prop"] = dict(record["prop"])
            record["prop"]["status"] = sheet_row["status"]

    props = []
    rea_new_cutoff = latest_ts - timedelta(days=rea_new_days)
    for sid, record in union.items():
        days_ago = max(0, (now - record["last_seen"]).days)
        p0 = record["prop"]
        listed_at = _parse_iso_datetime(p0.get("date_listed"))
        is_recent_rea = (
            _is_realestate_com_listing(p0)
            and listed_at is not None
            and listed_at >= rea_new_cutoff
        )
        p = dict(p0)
        if is_recent_rea:
            p["recent_realestate_com"] = True
        # Flag + day-count are separate so a same-day earlier-scrape prop still
        # registers as stale (days_ago can legitimately be 0 for today's 12pm run
        # when the 1:39pm run dropped it).
        if sid not in latest_ids:
            p["missing_from_latest"] = True
            p["last_seen_days"] = days_ago
        p["status"] = availability_status(
            p,
            missing_from_latest=sid not in latest_ids,
            missing_days=days_ago,
        )
        p["first_seen_days"] = max(0, (now - record["first_seen"]).days)
        props.append(p)

    return props, latest_file


if __name__ == "__main__":
    properties, latest_file = _load_union_of_runs(runs_to_union=3, age_out_days=21)

    if not properties or not latest_file:
        print("No search results found. Run search.py first.")
        sys.exit(1)

    stale_count = sum(1 for p in properties if p.get("missing_from_latest"))
    fresh_count = len(properties) - stale_count
    print(f"Loaded {len(properties)} properties ({fresh_count} from latest run, "
          f"{stale_count} carried over from prior runs within 21d)")
    results_files = [latest_file]  # downstream code only references [0]

    # Extract timestamp from filename: search_YYYYMMDD_HHMM.json → "17 March 2026 · 4:09pm"
    search_date = None
    stem = results_files[0].stem  # search_20260317_1609
    parts = stem.split("_")
    if len(parts) == 3:
        try:
            ts = datetime.strptime(f"{parts[1]}_{parts[2]}", "%Y%m%d_%H%M")
            search_date = ts.strftime("%-d %B %Y · %-I:%M%p").replace("AM", "am").replace("PM", "pm")
        except ValueError:
            pass

    try:
        with open(latest_file) as source_file:
            source_report = json.load(source_file).get("source_report") or {}
    except (OSError, ValueError):
        source_report = {}

    path = generate_shortlist(
        properties,
        search_date=search_date,
        source_report=source_report,
    )

    # Every public page reads this exact state. It is generated from the same
    # canonical partition as index.html and published in the same commit.
    try:
        with open(latest_file) as f:
            run_metadata = json.load(f)
    except (OSError, json.JSONDecodeError):
        run_metadata = {}
    from site_state import build_site_state, write_site_state
    active_props, archived_props, _ = _partition_props(properties)
    state_search_display = search_date or datetime.now().strftime("%d %B %Y")
    state = build_site_state(
        active_props,
        archived_props,
        search_display=state_search_display,
        run_metadata=run_metadata,
    )
    state_path = write_site_state(state)
    print(f"Site state: {state_path}")

    # `--mark-sent`: snapshot what George is receiving as the new baseline.
    # Run this only when actually sending — normal renders leave it untouched.
    if "--mark-sent" in sys.argv:
        visible = _visible_props(properties)
        ids = sorted({pid for p in visible
                      if (pid := (p.get("source_id") or p.get("id")))})
        with open(LAST_SENT_FILE, "w") as f:
            json.dump({"marked_at": datetime.now().isoformat(), "source_ids": ids},
                      f, indent=2)
        print(f"Marked sent: baseline = {len(ids)} source_ids → {LAST_SENT_FILE}")

    if "--open" in sys.argv:
        import subprocess
        subprocess.run(["open", str(path)])
