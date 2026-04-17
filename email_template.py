#!/usr/bin/env python3
"""
Email digest template — renders scored properties into a clean HTML email.

Usage:
    from email_template import render_email
    html = render_email(properties, search_date="2026-03-10")
"""

from datetime import datetime


def _score_bar(pct):
    """Render a score as a coloured bar."""
    if pct >= 70:
        color = "#16a34a"  # green
    elif pct >= 50:
        color = "#2563eb"  # blue
    elif pct >= 30:
        color = "#d97706"  # amber
    else:
        color = "#9ca3af"  # grey
    return f"""<div style="background:#e5e7eb;border-radius:4px;height:8px;width:100px;display:inline-block;vertical-align:middle;">
        <div style="background:{color};border-radius:4px;height:8px;width:{min(pct, 100)}px;"></div>
    </div>
    <span style="font-size:14px;font-weight:600;color:{color};margin-left:4px;">{pct:.0f}%</span>"""


def _drive_badge(mins):
    """Render drive time as a coloured badge."""
    if mins is None:
        return '<span style="color:#9ca3af;">—</span>'
    hours = mins / 60
    if hours <= 3:
        color, bg = "#166534", "#dcfce7"
    elif hours <= 3.5:
        color, bg = "#1e40af", "#dbeafe"
    elif hours <= 4:
        color, bg = "#92400e", "#fef3c7"
    else:
        color, bg = "#991b1b", "#fee2e2"
    h = int(hours)
    m = int(mins - h * 60)
    return f'<span style="background:{bg};color:{color};padding:2px 8px;border-radius:12px;font-size:13px;font-weight:500;">{h}h{m:02d}m</span>'


def _tag_pills(tags):
    """Render tags as small pills."""
    if not tags:
        return ""
    pills = []
    for tag in tags[:6]:  # max 6 tags
        label = tag.replace("_", " ").title()
        pills.append(f'<span style="background:#f1f5f9;color:#475569;padding:2px 8px;border-radius:10px;font-size:11px;margin-right:4px;">{label}</span>')
    return " ".join(pills)


def _property_card(prop, index):
    """Render a single property card."""
    score = prop.get("score", {})
    pct = score.get("pct", 0)
    price = prop.get("price")
    price_str = f"${price:,.0f}" if price else prop.get("display_price", "Price on application")
    acres = prop.get("land_acres")
    acres_str = f"{acres:.0f} acres" if acres else "—"
    beds = prop.get("bedrooms")
    baths = prop.get("bathrooms")
    bed_bath = ""
    if beds:
        bed_bath = f"{beds} bed"
        if baths:
            bed_bath += f" / {baths} bath"
    drive_mins = prop.get("drive_time_minutes")
    headline = prop.get("headline", "").strip().strip('"').strip("'").strip()
    description = prop.get("description", "")[:300]
    if len(prop.get("description", "")) > 300:
        description += "..."
    listing_url = prop.get("listing_url", "#")
    photo_url = prop.get("photo_url")
    tags = prop.get("tags", [])
    num = index + 1

    photo_html = ""
    if photo_url:
        photo_html = f'<img src="{photo_url}" alt="Property photo" style="width:100%;max-height:220px;object-fit:cover;border-radius:8px 8px 0 0;" />'

    return f"""
    <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;margin-bottom:24px;overflow:hidden;">
        {photo_html}
        <div style="padding:16px 20px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span style="font-size:13px;font-weight:700;color:#94a3b8;">#{num}</span>
                <span style="font-size:18px;font-weight:700;color:#1e293b;">{price_str}</span>
                {_score_bar(pct)}
            </div>
            <div style="font-size:15px;font-weight:600;color:#334155;margin-bottom:4px;">{headline}</div>
            <div style="font-size:13px;color:#64748b;margin-bottom:8px;">
                {prop.get('address', '')}
            </div>
            <div style="font-size:13px;color:#475569;margin-bottom:12px;">
                <span style="margin-right:16px;">{acres_str}</span>
                <span style="margin-right:16px;">{bed_bath}</span>
                {_drive_badge(drive_mins)}
            </div>
            <div style="font-size:13px;color:#64748b;line-height:1.5;margin-bottom:12px;">
                {description}
            </div>
            <div style="margin-bottom:12px;">{_tag_pills(tags)}</div>
            <div>
                <a href="{listing_url}" style="display:inline-block;background:#1e293b;color:#ffffff;padding:8px 20px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:500;">View Listing</a>
            </div>
        </div>
    </div>"""


def _summary_row(prop, index):
    """Render a compact table row for the 'also worth a look' section."""
    num = index + 1
    pct = prop.get("score", {}).get("pct", 0)
    price = prop.get("price")
    price_str = f"${price:,.0f}" if price else prop.get("display_price", "POA")[:16]
    acres = f"{prop.get('land_acres', 0):.0f}ac" if prop.get("land_acres") else "—"
    suburb = prop.get("suburb", "")
    headline = (prop.get("headline", "") or "").strip().strip('"').strip("'").strip()
    if len(headline) > 40:
        headline = headline[:38] + "..."
    listing_url = prop.get("listing_url", "#")
    drive_mins = prop.get("drive_time_minutes")
    drive_str = ""
    if drive_mins:
        h = int(drive_mins // 60)
        m = int(drive_mins % 60)
        drive_str = f"{h}h{m:02d}"

    if pct >= 70:
        score_color = "#16a34a"
    elif pct >= 50:
        score_color = "#2563eb"
    else:
        score_color = "#d97706"

    return f"""<tr style="border-bottom:1px solid #f1f5f9;">
        <td style="padding:8px 6px;font-size:13px;color:#94a3b8;font-weight:600;">#{num}</td>
        <td style="padding:8px 6px;font-size:13px;">
            <a href="{listing_url}" style="color:#1e293b;text-decoration:none;font-weight:500;">{headline}</a>
            <div style="font-size:11px;color:#94a3b8;">{suburb}</div>
        </td>
        <td style="padding:8px 6px;font-size:13px;color:#334155;text-align:right;">{price_str}</td>
        <td style="padding:8px 6px;font-size:13px;color:#64748b;text-align:right;">{acres}</td>
        <td style="padding:8px 6px;font-size:13px;color:#64748b;text-align:right;">{drive_str}</td>
        <td style="padding:8px 6px;font-size:13px;font-weight:600;color:{score_color};text-align:right;">{pct:.0f}%</td>
    </tr>"""


def render_email(properties, search_date=None, card_count=10):
    """Render the full email HTML.

    Args:
        properties: scored property list, already sorted by score desc
        search_date: display date string
        card_count: number of full photo cards (remaining shown as compact table)
    """
    if search_date is None:
        search_date = datetime.now().strftime("%d %B %Y")

    total_count = len(properties)
    count = total_count
    if count == 0:
        summary = "No new properties matched your criteria this week."
    elif count == 1:
        summary = "1 new property matched your criteria this week."
    else:
        summary = f"{count} new properties matched your criteria this week."

    # Best score highlight
    top_score = ""
    if properties:
        best = properties[0]
        top_score = f'Top match: <strong>{best.get("headline", "")[:50]}</strong> ({best["score"]["pct"]:.0f}% fit)'

    # Split into cards + table
    card_props = properties[:card_count]
    table_props = properties[card_count:]

    cards_html = ""
    for i, prop in enumerate(card_props):
        cards_html += _property_card(prop, i)

    # Compact summary table for the rest
    table_html = ""
    if table_props:
        rows = ""
        for i, prop in enumerate(table_props):
            rows += _summary_row(prop, card_count + i)
        table_html = f"""
        <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:16px 20px;margin-bottom:24px;">
            <div style="font-size:16px;font-weight:700;color:#1e293b;margin-bottom:12px;">Also worth a look</div>
            <table style="width:100%;border-collapse:collapse;">
                <tr style="border-bottom:2px solid #e2e8f0;">
                    <th style="padding:6px;font-size:11px;color:#94a3b8;text-align:left;font-weight:600;text-transform:uppercase;">#</th>
                    <th style="padding:6px;font-size:11px;color:#94a3b8;text-align:left;font-weight:600;text-transform:uppercase;">Property</th>
                    <th style="padding:6px;font-size:11px;color:#94a3b8;text-align:right;font-weight:600;text-transform:uppercase;">Price</th>
                    <th style="padding:6px;font-size:11px;color:#94a3b8;text-align:right;font-weight:600;text-transform:uppercase;">Land</th>
                    <th style="padding:6px;font-size:11px;color:#94a3b8;text-align:right;font-weight:600;text-transform:uppercase;">Drive</th>
                    <th style="padding:6px;font-size:11px;color:#94a3b8;text-align:right;font-weight:600;text-transform:uppercase;">Fit</th>
                </tr>
                {rows}
            </table>
        </div>"""

    # Build the shortlist URL
    import os
    shortlist_url = os.getenv("SHORTLIST_URL", "https://karl-reforged.github.io/edm-shortlist/")

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bolt Hole — Property Shortlist</title>
</head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
    <div style="max-width:640px;margin:0 auto;padding:24px 16px;">

        <!-- Header -->
        <div style="text-align:center;margin-bottom:32px;">
            <div style="font-size:12px;font-weight:600;letter-spacing:2px;color:#94a3b8;text-transform:uppercase;margin-bottom:4px;">Reforged</div>
            <div style="font-size:24px;font-weight:700;color:#1e293b;">Bolt Hole — Weekly Shortlist</div>
            <div style="font-size:14px;color:#64748b;margin-top:4px;">{search_date}</div>
        </div>

        <!-- Intro -->
        <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:16px 20px;margin-bottom:24px;">
            <div style="font-size:14px;color:#334155;line-height:1.6;">
                George &amp; Mary,<br><br>
                Here are the top {count} from {summary.split()[0]} properties the system picked up this week.
                Each one is scored against your criteria &mdash; water, terrain, seclusion, house, and drive time &mdash;
                so the highest-scoring properties should feel closest to what you're after.<br><br>
                The full list with map is at
                <a href="{shortlist_url}" style="color:#2563eb;text-decoration:none;font-weight:500;">{shortlist_url}</a>
            </div>
        </div>

        <!-- Summary -->
        <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:16px 20px;margin-bottom:24px;">
            <div style="font-size:15px;color:#334155;">{summary}</div>
            <div style="font-size:13px;color:#64748b;margin-top:4px;">{top_score}</div>
        </div>

        <!-- Property Cards -->
        {cards_html}

        <!-- Also worth a look (compact table) -->
        {table_html}

        <!-- Feedback section -->
        <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
            <div style="font-size:16px;font-weight:700;color:#1e293b;margin-bottom:12px;">Your feedback shapes next week</div>
            <div style="font-size:14px;color:#334155;line-height:1.6;margin-bottom:16px;">
                Just reply to this email with any thoughts. Even a quick note helps me tune the system.
                Here's an example of the kind of thing that's useful:
            </div>
            <div style="background:#f8fafc;border-left:3px solid #94a3b8;padding:12px 16px;font-size:13px;color:#475569;line-height:1.6;margin-bottom:16px;">
                <em>
                #1 &mdash; Love it. Creek frontage is exactly what we're looking for.<br>
                #4 &mdash; Interesting but only 30 acres feels small.<br>
                #6 &mdash; Too close to the highway, we want more seclusion.<br>
                #9 &mdash; Tarago area is good, keep looking there.<br>
                General &mdash; Can you weight properties with existing dams higher?
                </em>
            </div>
            <div style="font-size:13px;color:#64748b;line-height:1.5;">
                Anything goes &mdash; thumbs up, thumbs down, "more like #2", "less like #7",
                or just "looks good, keep going". It all feeds back in.
            </div>
        </div>

        <!-- How it works / limitations -->
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
            <div style="font-size:16px;font-weight:700;color:#1e293b;margin-bottom:12px;">How this works</div>
            <div style="font-size:13px;color:#475569;line-height:1.7;">
                The system pulls listings from <strong>Domain</strong>, <strong>REA / realestate.com.au</strong>,
                <strong>Elders</strong>, <strong>Farmbuy</strong>, and <strong>Southern Tablelands Realty</strong>,
                then scores each one against your criteria &mdash; water (25), drive time (20),
                terrain (20), seclusion (15), house (15), and national park (5).<br><br>
                Scoring is based on keywords in the listing description, so it's not perfect &mdash;
                a property with "dam" in the text scores for water, but one that has a dam and doesn't
                mention it will be underscored. Your feedback helps me catch what the keywords miss.
            </div>
            <div style="font-size:14px;font-weight:600;color:#1e293b;margin-top:16px;margin-bottom:8px;">What's not in yet</div>
            <div style="font-size:13px;color:#475569;line-height:1.7;">
                <strong>Off-market channels</strong> &mdash; Listing Loop and Property Whispers accounts are set up but not yet feeding in automatically.<br>
                <strong>Satellite/spatial data</strong> &mdash; watercourse proximity, mobile coverage, neighbour density. These would improve scoring accuracy. On the roadmap.
            </div>
        </div>

        <!-- Footer -->
        <div style="text-align:center;padding:24px 0;border-top:1px solid #e2e8f0;margin-top:16px;">
            <div style="font-size:12px;color:#94a3b8;margin-top:8px;">
                Prepared by Karl Howard &middot; Reforged
            </div>
        </div>

    </div>
</body>
</html>"""


# ── Preview mode ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    from pathlib import Path

    # Load most recent search results
    results_dir = Path(__file__).parent / "data" / "listings"
    results_files = sorted(results_dir.glob("search_*.json"), reverse=True)

    if results_files:
        with open(results_files[0]) as f:
            data = json.load(f)
        properties = data.get("properties", [])
        print(f"Loaded {len(properties)} properties from {results_files[0].name}")
    else:
        # Demo data for preview
        properties = [
            {
                "address": "123 Example Rd, Oberon NSW 2787",
                "suburb": "Oberon",
                "price": 850000,
                "display_price": "$850,000",
                "land_acres": 120,
                "bedrooms": 3,
                "bathrooms": 1,
                "headline": "Stunning Rural Retreat with Creek Frontage",
                "description": "Set on 120 acres of undulating country with permanent creek frontage and panoramic valley views. The charming 3-bedroom homestead sits on an elevated position overlooking the property. Features include established gardens, machinery shed, and several dams.",
                "listing_url": "https://www.domain.com.au/example",
                "photo_url": None,
                "drive_time_minutes": 174,
                "tags": ["creek_frontage", "dam", "views", "existing_house", "existing_shed", "established_gardens"],
                "score": {"total": 72.5, "max_possible": 100, "pct": 72.5, "breakdown": {}},
            },
            {
                "address": "456 Rural Lane, Goulburn NSW 2580",
                "suburb": "Goulburn",
                "price": 1250000,
                "display_price": "$1,250,000",
                "land_acres": 85,
                "bedrooms": 4,
                "bathrooms": 2,
                "headline": "Private Grazing Property with Mountain Views",
                "description": "Secluded 85-acre grazing property at the end of a no-through road. 4-bedroom renovated farmhouse with north-facing living areas. Backs onto State Forest. Two bores and three dams provide year-round water.",
                "listing_url": "https://www.domain.com.au/example2",
                "photo_url": None,
                "drive_time_minutes": 158,
                "tags": ["bore", "dam", "end_of_road", "north_facing", "state_forest_adjacent", "existing_house", "cleared_pastoral"],
                "score": {"total": 65.0, "max_possible": 100, "pct": 65.0, "breakdown": {}},
            },
        ]
        print("Using demo data (no search results found)")

    html = render_email(properties)
    outfile = Path(__file__).parent / "email_preview.html"
    with open(outfile, "w") as f:
        f.write(html)
    print(f"Preview saved to {outfile}")
