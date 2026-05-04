#!/usr/bin/env python3
"""
Shortlist page generator — renders scored properties into a self-contained
HTML page hosted on GitHub Pages. George opens the link, browses, taps
feedback, favourites properties, leaves comments. All interactions log to
Google Sheet via Apps Script.

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
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "data" / "listings"
DOCS_DIR = BASE_DIR / "docs"
DOCS_DIR.mkdir(exist_ok=True)

FEEDBACK_URL = os.getenv("FEEDBACK_SCRIPT_URL", "")
NOTES_URL = os.getenv(
    "NOTES_SCRIPT_URL",
    "https://script.google.com/macros/s/AKfycby1EpSp4aOX0UdSLwRgLyDOBCfL7VBRhr_AsIwLQw8gnE3ds37c9-ducakspntlKpPb/exec",
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


def generate_shortlist(properties, search_date=None, max_properties=None, output_path=None):
    if search_date is None:
        search_date = datetime.now().strftime("%d %B %Y")
    if output_path is None:
        output_path = DOCS_DIR / "index.html"

    props = properties[:max_properties] if max_properties else properties
    total_found = len(properties)
    total_shown = len(props)
    sources_count = len({p.get("source") for p in properties if p.get("source")})

    # Detect new listings by comparing against previous run
    new_ids = set()
    prev_files = sorted(RESULTS_DIR.glob("search_*.json"), reverse=True)
    if len(prev_files) >= 2:
        try:
            with open(prev_files[1]) as f:
                prev_data = json.load(f)
            prev_ids = {p.get("source_id") or p.get("id") for p in prev_data.get("properties", [])}
            for p in props:
                pid = p.get("source_id") or p.get("id")
                if pid and pid not in prev_ids:
                    new_ids.add(pid)
        except Exception:
            pass

    # ── Build cards HTML ──────────────────────────────────────────────────
    cards_html = []
    for i, p in enumerate(props):
        score = p.get("score", {})
        pct = score.get("pct", 0)
        breakdown = score.get("breakdown", {})
        max_possible = score.get("max_possible", 100)
        sc_color, sc_bg = _score_color(pct)

        price = p.get("price")
        price_str = f"${price:,.0f}" if price else _escape(p.get("display_price", "Price on application"))

        acres = p.get("land_acres")
        acres_str = f"{acres:.0f} acres" if acres else ""

        beds = p.get("bedrooms")
        baths = p.get("bathrooms")
        bed_bath = ""
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
        description = _escape(p.get("description", "")[:400])
        if len(p.get("description", "")) > 400:
            description += "..."

        listing_url = _escape(p.get("listing_url", "#"))
        photo_url = p.get("photo_url")

        photo_html = ""
        if photo_url:
            photo_html = f'<div class="card-photo"><img src="{_escape(photo_url)}" alt="" loading="lazy" /></div>'

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
        is_new = 1 if (prop_id in new_ids and not missing_from_latest) else 0
        cards_html.append(f'''
        <div class="card" id="card-{i}" data-idx="{i}" data-property-id="{prop_id}" data-score="{pct:.1f}" data-price="{price or 0}" data-acres="{acres or 0}" data-drive="{drive_mins or 9999}" data-new="{is_new}" data-ppa="{ppa:.0f}" {stale_attr}>
            {photo_html}
            <div class="card-body">
                <div class="card-top-row">
                    <div class="card-header">
                        <span class="rank-badge" style="background:{sc_color};" onclick="panMapToCard({i})" title="Tap to find on map">#{i+1}</span>
                        <span class="price">{price_str}</span>
                        {"<span class='new-badge'>NEW</span>" if is_new else ""}<button class="score-badge" style="color:{sc_color};background:{sc_bg};" onclick="toggleBreakdown({i})" title="Tap to see score breakdown">{pct:.0f}% match</button>
                    </div>
                    <button class="fav-btn" id="fav-{i}" onclick="toggleFavourite({i}, '{prop_id}')" title="Favourite">
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
                    <a href="{listing_url}" target="_blank" rel="noopener" class="btn btn-view">View Listing</a>
                    <div class="feedback" id="feedback-{i}">
                        <button class="btn btn-love" onclick="sendFeedback({i}, '{prop_id}', 'love')">Love it</button>
                        <button class="btn btn-interesting" onclick="sendFeedback({i}, '{prop_id}', 'interesting')">Interesting</button>
                        <button class="btn btn-pass" onclick="sendFeedback({i}, '{prop_id}', 'pass')">Not for me</button>
                    </div>
                </div>
                <div class="notes-section" id="notes-section-{i}" data-property-id="{prop_id}">
                    <button class="notes-pill notes-pill-empty" onclick="toggleNotes({i})">+ note</button>
                    <div class="notes-drawer" id="notes-drawer-{i}" style="display:none;">
                        <div class="notes-list" id="notes-list-{i}"></div>
                        <div class="notes-input-row">
                            <input type="text" class="notes-input" id="notes-input-{i}" placeholder="Add a note…" maxlength="500" onkeydown="noteKeydown(event, {i}, '{prop_id}')">
                            <button class="notes-post" onclick="submitNote({i}, '{prop_id}')">Post</button>
                        </div>
                    </div>
                </div>
                <div class="feedback-confirmation" id="confirm-{i}" style="display:none;"></div>
            </div>
        </div>''')

    all_cards = "\n".join(cards_html)

    # ── Summary ───────────────────────────────────────────────────────────
    if max_properties and total_found > max_properties:
        showing = f"Showing top {max_properties} of {total_found} matches"
    else:
        showing = f"{total_found} properties matched your criteria"

    # ── Scrape status strip ──────────────────────────────────────────────
    # Pull source_report from the most recent cached run so we can surface
    # raw-listing counts, dormant sources, and source errors.
    status_bits = []
    raw_total = 0
    errored_sources = []
    dormant_sources = []
    try:
        if prev_files:
            with open(prev_files[0]) as _f:
                _latest = json.load(_f)
            sr = _latest.get("source_report") or {}
            for name, rep in sr.items():
                c = rep.get("count", 0)
                if rep.get("error"):
                    errored_sources.append(name)
                elif c == 0 and name not in ("Domain API", "REA Manual"):
                    # "Domain API" is intentionally null (falls back to Domain Web);
                    # "REA Manual" is user-populated, blank is normal.
                    dormant_sources.append(name)
                raw_total += c
    except Exception:
        pass

    if raw_total:
        status_bits.append(f"{raw_total} listings scanned")
    status_bits.append(f"{total_found} passed")
    if new_ids:
        status_bits.append(f"{len(new_ids)} new")
    if dormant_sources:
        status_bits.append(f'<span class="scrape-status-warn" title="Source returned 0 listings this run">{", ".join(dormant_sources)} idle</span>')
    if errored_sources:
        status_bits.append(f'<span class="scrape-status-warn" title="Source reported an error this run">{", ".join(errored_sources)} errored</span>')
    scrape_status_html = " &middot; ".join(status_bits)

    best = props[0] if props else None
    top_match = ""
    if best:
        top_match = f'Top match: {_escape(best.get("headline", "")[:60])} ({best["score"]["pct"]:.0f}%)'

    new_count = len(new_ids)

    feedback_url_js = _escape(FEEDBACK_URL) if FEEDBACK_URL else ""
    notes_url_js = _escape(NOTES_URL) if NOTES_URL else ""

    # ── Map markers JSON ──────────────────────────────────────────────────
    mapped_props = [(i, p) for i, p in enumerate(props) if p.get("lat") and p.get("lng")]
    total_count = len(props)
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
    <title>Bolt Hole — Weekly Shortlist</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
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

        /* ── Scrape status strip ─────────────────── */
        .scrape-status {{
            font-size: 11px; color: var(--slate);
            padding: 8px 20px 0; margin: -14px 0 18px;
            opacity: 0.85;
        }}
        .scrape-status-warn {{
            color: #b45309; font-weight: 500;
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
            white-space: nowrap; transition: all 0.15s;
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
            min-width: 24px; height: 24px; padding: 0 7px;
            font-size: 12px; font-weight: 700; color: #fff;
            border-radius: 12px; margin-right: 8px;
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
        .popup-link {{ color: var(--eucalyptus); font-weight: 600; text-decoration: none; cursor: pointer; }}

        /* ── Cards ───────────────────────────────── */
        .card {{
            background: #fff; border: 1px solid var(--light-border);
            border-radius: 10px; margin-bottom: 24px; overflow: hidden;
            transition: box-shadow 0.2s, opacity 0.4s, border-color 0.3s;
        }}
        .card:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.06); }}
        .card.dismissed {{ opacity: 0.35; display: none; }}
        .card.dismissed.show-dismissed {{ display: block; }}
        .card.dismissed:hover {{ opacity: 0.6; }}

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

        .card-photo {{ overflow: hidden; }}
        .card-photo img {{ width: 100%; max-height: 240px; object-fit: cover; display: block; }}
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
        <a href="bolt-hole-overview.html" style="display:inline-flex;align-items:center;padding:14px 12px;font-size:13px;font-weight:500;color:#64748b;text-decoration:none;white-space:nowrap;border-bottom:2px solid transparent;min-height:48px;">Overview</a>
        <a href="dashboard.html" style="display:inline-flex;align-items:center;padding:14px 12px;font-size:13px;font-weight:500;color:#64748b;text-decoration:none;white-space:nowrap;border-bottom:2px solid transparent;min-height:48px;">Market Map</a>
        <a href="./" style="display:inline-flex;align-items:center;padding:14px 12px;font-size:13px;font-weight:600;color:#4A7C6B;text-decoration:none;white-space:nowrap;border-bottom:2px solid #4A7C6B;min-height:48px;">Shortlist</a>
        <a href="system-map.html" style="display:inline-flex;align-items:center;padding:14px 12px;font-size:13px;font-weight:500;color:#64748b;text-decoration:none;white-space:nowrap;border-bottom:2px solid transparent;min-height:48px;">How It Works</a>
      </div>
    </nav>
    <div class="container">

        <div class="header">
            <div class="brand">Bolt Hole Search</div>
            <h1>Bolt Hole &mdash; Weekly Shortlist</h1>
            <div class="date">{_escape(search_date)}</div>
            <div class="freshness">{total_found} properties &middot; {sources_count} sources</div>
        </div>

        <div class="summary">
            <div class="count">{showing}</div>
            <div class="top">{top_match}</div>
        </div>

        <div class="scrape-status">{scrape_status_html}</div>
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
                    <button type="button" class="map-expand-btn" onclick="openExpandedMap()" title="Open full-screen map">Expand &nearr;</button>
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

        {all_cards}

        <div class="footer">
            <p>Tap <strong>Love it</strong>, <strong>Interesting</strong>, or <strong>Not for me</strong> &mdash; your feedback sharpens next week's results.</p>
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
        const cards = Array.from(container.querySelectorAll('.card'));
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

    const FEEDBACK_URL = "{feedback_url_js}";
    const NOTES_URL = "{notes_url_js}";
    const TOTAL = {total_shown};
    const state = {{
        feedback: {{}},    // idx -> reaction
        favourites: {{}},  // idx -> true
        reviewed: 0,
        favCount: 0,
    }};

    // ── Persist to localStorage so scroll-back shows state ──────────
    function saveState() {{
        try {{ localStorage.setItem('blh_state', JSON.stringify(state)); }} catch(e) {{}}
    }}
    function loadState() {{
        try {{
            const s = localStorage.getItem('blh_state');
            if (s) {{
                const saved = JSON.parse(s);
                Object.assign(state, saved);
                // Restore UI
                Object.entries(state.feedback).forEach(([idx, reaction]) => {{
                    applyFeedbackUI(parseInt(idx), reaction);
                }});
                Object.entries(state.favourites).forEach(([idx, isFav]) => {{
                    if (isFav) applyFavouriteUI(parseInt(idx));
                }});
                updateProgress();
            }}
        }} catch(e) {{}}
    }}

    // ── Feedback ──────────────────────────────────────────────────────
    function sendFeedback(idx, propertyId, reaction) {{
        // Clicking an already-selected reaction clears it (neutral)
        const effective = state.feedback[idx] === reaction ? null : reaction;

        if (effective === null) {{
            delete state.feedback[idx];
        }} else {{
            state.feedback[idx] = effective;
        }}
        state.reviewed = Object.keys(state.feedback).length;
        applyFeedbackUI(idx, effective);
        updateProgress();
        saveState();

        if (FEEDBACK_URL) {{
            const url = FEEDBACK_URL + '?action=feedback'
                + '&property_id=' + encodeURIComponent(propertyId)
                + '&reaction=' + encodeURIComponent(effective === null ? 'clear' : effective);
            fetch(url, {{ mode: 'no-cors' }}).catch(() => {{}});
        }}
    }}

    function applyFeedbackUI(idx, reaction) {{
        const card = document.getElementById('card-' + idx);
        const container = document.getElementById('feedback-' + idx);
        if (!container || !card) return;

        // Button highlighting — reaction of null clears all
        const buttons = container.querySelectorAll('button');
        buttons.forEach(btn => {{
            btn.classList.remove('selected');
            const text = btn.textContent.toLowerCase();
            if ((reaction === 'love' && text.includes('love')) ||
                (reaction === 'interesting' && text.includes('interesting')) ||
                (reaction === 'pass' && text.includes('not'))) {{
                btn.classList.add('selected');
            }}
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
        showConfirmation(idx, msg);

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
            const activeCards = Array.from(container.querySelectorAll('.card:not(.dismissed)'));
            const myScore = parseFloat(card.dataset.score) || 0;
            const insertBefore = activeCards.find(c => c !== card && (parseFloat(c.dataset.score) || 0) < myScore);
            if (insertBefore) {{
                container.insertBefore(card, insertBefore);
            }}
        }}
    }}

    function updateDismissedCount() {{
        const dismissed = document.querySelectorAll('.card.dismissed');
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
        const dismissed = document.querySelectorAll('.card.dismissed');
        const btn = document.querySelector('.dismissed-toggle');
        const showing = btn.textContent === 'Hide';
        dismissed.forEach(c => c.classList.toggle('show-dismissed', !showing));
        btn.textContent = showing ? 'Show' : 'Hide';
    }}

    // ── Favourites ────────────────────────────────────────────────────
    function toggleFavourite(idx, propertyId) {{
        const isFav = !state.favourites[idx];
        state.favourites[idx] = isFav;
        state.favCount = Object.values(state.favourites).filter(Boolean).length;

        if (isFav) {{
            applyFavouriteUI(idx);
        }} else {{
            removeFavouriteUI(idx);
        }}
        updateProgress();
        saveState();

        if (FEEDBACK_URL) {{
            const url = FEEDBACK_URL + '?action=favourite'
                + '&property_id=' + encodeURIComponent(propertyId)
                + '&value=' + (isFav ? '1' : '0');
            fetch(url, {{ mode: 'no-cors' }}).catch(() => {{}});
        }}
    }}

    function applyFavouriteUI(idx) {{
        const card = document.getElementById('card-' + idx);
        const btn = document.getElementById('fav-' + idx);
        if (card) card.classList.add('favourited');
        if (btn) btn.classList.add('active');
        // Update map pin
        const pinEl = document.querySelector('.map-pin[data-idx="' + idx + '"]');
        if (pinEl) pinEl.classList.add('fav-pin');
    }}

    function removeFavouriteUI(idx) {{
        const card = document.getElementById('card-' + idx);
        const btn = document.getElementById('fav-' + idx);
        if (card) card.classList.remove('favourited');
        if (btn) btn.classList.remove('active');
        const pinEl = document.querySelector('.map-pin[data-idx="' + idx + '"]');
        if (pinEl) pinEl.classList.remove('fav-pin');
    }}

    // ── Score breakdown toggle ────────────────────────────────────────
    function toggleBreakdown(idx) {{
        const el = document.getElementById('breakdown-' + idx);
        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
    }}

    // ── Shared notes (Apps Script backend) ────────────────────────────
    // No identity plumbing — one URL for everyone, sign off inside the note
    // body if you want ("— George"). The sheet's author column stays as
    // dead data for existing test rows.
    let notesCache = {{}};

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

    function loadNotes() {{
        if (!NOTES_URL) return;
        fetch(NOTES_URL).then(r => r.json()).then(data => {{
            const next = {{}};
            (data.notes || []).forEach(n => {{
                (next[n.property_id] = next[n.property_id] || []).push(n);
            }});
            // Preserve optimistic (local-*) notes the server hasn't echoed back yet,
            // to avoid flashing away a user's fresh note during the write race window.
            Object.entries(notesCache).forEach(([pid, arr]) => {{
                const pendingLocals = arr.filter(n =>
                    typeof n.id === 'string' && n.id.startsWith('local-'));
                if (!pendingLocals.length) return;
                const serverTexts = new Set((next[pid] || []).map(n =>
                    (n.note || '') + '|' + (n.author || '')));
                const stillPending = pendingLocals.filter(n =>
                    !serverTexts.has((n.note || '') + '|' + (n.author || '')));
                if (stillPending.length) {{
                    next[pid] = [...(next[pid] || []), ...stillPending];
                }}
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
        }}).catch(e => console.warn('notes load failed', e));
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
                '<span class="note-time">' + escapeHtml(formatNoteDate(n.timestamp)) + '</span>' +
            '</div><div class="note-body">' + escapeHtml(n.note) + '</div></div>'
        )).join('');
    }}

    function toggleNotes(idx) {{
        const drawer = document.getElementById('notes-drawer-' + idx);
        if (!drawer) return;
        const isOpen = drawer.style.display === 'block';
        drawer.style.display = isOpen ? 'none' : 'block';
        if (!isOpen) {{
            const input = document.getElementById('notes-input-' + idx);
            if (input) input.focus();
        }}
    }}

    function submitNote(idx, propertyId) {{
        const input = document.getElementById('notes-input-' + idx);
        if (!input) return;
        const text = (input.value || '').trim();
        if (!text || !NOTES_URL) return;

        const optimistic = {{
            id: 'local-' + Date.now(),
            property_id: propertyId,
            author: '',
            timestamp: new Date().toISOString(),
            note: text,
        }};
        (notesCache[propertyId] = notesCache[propertyId] || []).push(optimistic);
        renderNotesIntoCard(idx, notesCache[propertyId]);
        input.value = '';

        fetch(NOTES_URL, {{
            method: 'POST',
            body: JSON.stringify({{action:'note', property_id: propertyId, author: '', note: text}}),
        }}).then(() => setTimeout(loadNotes, 2500)).catch(e => console.warn('note post failed', e));
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
            return '<div class="activity-item" onclick="scrollToProperty(\\'' + pidAttr.replace(/'/g, "\\\\'") + '\\')">' +
                '<div class="activity-meta">' +
                    '<span class="activity-suburb">' + escapeHtml(addr || '—') + '</span> · ' +
                    '<span class="note-time">' + escapeHtml(formatNoteDate(n.timestamp)) + '</span>' +
                '</div><div class="activity-body">' + escapeHtml(n.note) + '</div></div>';
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

    function scrollToCard(idx) {{
        const card = document.getElementById('card-' + idx);
        if (card) card.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
    }}

    function pulsePin(idx) {{
        const pin = mapPinEls[idx];
        if (!pin) return;
        pin.classList.remove('pulse');
        void pin.offsetWidth; // reflow to restart animation
        pin.classList.add('pulse');
    }}

    function panMapToCard(idx) {{
        const marker = mapMarkers[idx];
        if (!marker || !map) return;
        const mapEl = document.getElementById('shortlist-map');
        if (mapEl) mapEl.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
        // Defer pan/zoom until the smooth-scroll has settled so the popup
        // anchors correctly relative to the now-visible map viewport.
        setTimeout(() => {{
            const targetZoom = Math.max(map.getZoom(), 11);
            map.flyTo(marker.getLatLng(), targetZoom, {{ duration: 0.7 }});
            marker.openPopup();
            pulsePin(idx);
        }}, 350);
    }}

    function updateMapPin(idx, reaction) {{
        const marker = mapMarkers[idx];
        const pin = mapPinEls[idx];
        if (reaction === 'pass') {{
            // Remove from map entirely
            if (marker && map) map.removeLayer(marker);
        }} else {{
            // Add back if was removed
            if (marker && map && !map.hasLayer(marker)) map.addLayer(marker);
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

    let map;
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

        markersData.forEach(m => {{
            const color = pinColor(m.pct);
            const icon = L.divIcon({{
                className: '',
                html: '<div class="map-pin" data-idx="' + m.idx + '" style="background:' + color + ';">' + (m.idx + 1) + '</div>',
                iconSize: [28, 28],
                iconAnchor: [14, 14],
                popupAnchor: [0, -16]
            }});

            const marker = L.marker([m.lat, m.lng], {{ icon: icon }}).addTo(map);
            marker.bindPopup(
                '<strong>' + m.suburb + '</strong><br>' +
                m.price + (m.acres ? ' &middot; ' + m.acres : '') +
                ' &middot; ' + m.pct.toFixed(0) + '%<br>' +
                '<a class="popup-link" onclick="scrollToCard(' + m.idx + ')">Jump to card &darr;</a>'
            );

            mapMarkers[m.idx] = marker;
            bounds.push([m.lat, m.lng]);

            // Grab pin DOM reference after it renders
            marker.on('add', () => {{
                setTimeout(() => {{
                    const el = document.querySelector('.map-pin[data-idx="' + m.idx + '"]');
                    if (el) mapPinEls[m.idx] = el;
                }}, 50);
            }});
        }});

        map.fitBounds(bounds, {{ padding: [30, 30] }});
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
    function openExpandedMap() {{
        const modal = document.getElementById('map-modal');
        if (!modal) return;
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        if (!expandedMap && typeof markersData !== 'undefined' && markersData.length > 0) {{
            expandedMap = L.map('expanded-map', {{ zoomControl: true, attributionControl: false }});
            L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}@2x.png', {{
                maxZoom: 14, attribution: '&copy; OSM &amp; CARTO'
            }}).addTo(expandedMap);
            L.circleMarker([-33.8688, 151.2653], {{
                radius: 5, fillColor: '#ef4444', fillOpacity: 0.9, color: '#fff', weight: 2
            }}).addTo(expandedMap).bindPopup('<strong>Sydney</strong><br>Reference point');
            const eb = [[-33.8688, 151.2653]];
            markersData.forEach(m => {{
                const color = pinColor(m.pct);
                const icon = L.divIcon({{
                    className: '',
                    html: '<div class="map-pin" style="background:' + color + ';">' + (m.idx + 1) + '</div>',
                    iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -16]
                }});
                const marker = L.marker([m.lat, m.lng], {{ icon: icon }}).addTo(expandedMap);
                marker.bindPopup(
                    '<strong>' + m.suburb + '</strong><br>' +
                    m.price + (m.acres ? ' &middot; ' + m.acres : '') +
                    ' &middot; ' + m.pct.toFixed(0) + '%<br>' +
                    '<a class="popup-link" onclick="closeExpandedMap(); scrollToCard(' + m.idx + ')">Jump to card &darr;</a>'
                );
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
    }}
    (function wireExpandedMap() {{
        const modal = document.getElementById('map-modal');
        if (!modal) return;
        modal.addEventListener('click', e => {{ if (e.target === modal) closeExpandedMap(); }});
        document.addEventListener('keydown', e => {{
            if (e.key === 'Escape' && !modal.classList.contains('hidden')) closeExpandedMap();
        }});
    }})();

    // ── Restore state on load ─────────────────────────────────────────
    loadState();
    loadNotes();
    </script>
</body>
</html>'''

    with open(output_path, "w") as f:
        f.write(page_html)

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
    Fetch properties from the Apps Script sheet (self-contained DB) keyed by
    source_id. Returns {} if endpoint is absent, action is unimplemented,
    or any network hiccup. Never raises — sheet is a bonus, JSONs are canon.
    """
    url = os.getenv(
        "NOTES_SCRIPT_URL",
        "https://script.google.com/macros/s/AKfycby1EpSp4aOX0UdSLwRgLyDOBCfL7VBRhr_AsIwLQw8gnE3ds37c9-ducakspntlKpPb/exec",
    )
    if not url:
        return {}
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(url + "?action=properties", timeout=8) as resp:
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


def _load_union_of_runs(runs_to_union=3, age_out_days=21):
    """
    Union properties across the N most-recent scrape JSONs by source_id, then
    overlay any sheet-only properties still within the age-out window. Local
    JSON data wins when present (freshest). Properties missing from the
    latest run get 'missing_from_latest' + 'last_seen_days' so the UI can
    mark them stale. Returns (props_list, latest_file).
    """
    results_files = sorted(RESULTS_DIR.glob("search_*.json"), reverse=True)
    if not results_files:
        return [], None

    latest_file = results_files[0]
    latest_ts = _parse_run_timestamp(latest_file.stem) or datetime.now()
    latest_ids = set()
    union = {}  # source_id -> {"prop": dict, "last_seen": datetime}

    # Iterate newest-first so newer data wins on first-seen
    for fp in results_files[:runs_to_union]:
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
                union[sid] = {"prop": p, "last_seen": run_ts or latest_ts}

    # Sheet overlay — fills gaps for properties not present in local JSONs but
    # recorded in the sheet (e.g. other machines, or runs deleted from disk).
    now = datetime.now()
    sheet_props = _fetch_sheet_properties()
    sheet_added = 0
    for sid, row in sheet_props.items():
        if sid in union:
            continue
        # Status column supports manual age-out (set to "withdrawn"/"sold")
        if row.get("status") and row["status"] not in ("active", "", None):
            continue
        payload = row.get("payload")
        if isinstance(payload, dict) and payload:
            prop = payload
        else:
            continue
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
        union[sid] = {"prop": prop, "last_seen": last_seen}
        sheet_added += 1
    if sheet_added:
        print(f"Sheet overlay: +{sheet_added} properties not in local runs")

    props = []
    for sid, record in union.items():
        days_ago = max(0, (now - record["last_seen"]).days)
        if days_ago > age_out_days:
            continue
        p = dict(record["prop"])
        # Flag + day-count are separate so a same-day earlier-scrape prop still
        # registers as stale (days_ago can legitimately be 0 for today's 12pm run
        # when the 1:39pm run dropped it).
        if sid not in latest_ids:
            p["missing_from_latest"] = True
            p["last_seen_days"] = days_ago
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

    path = generate_shortlist(properties, search_date=search_date)

    if "--open" in sys.argv:
        import subprocess
        subprocess.run(["open", str(path)])
