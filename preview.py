#!/usr/bin/env python3
"""
Reusable weekly workflow — run pipeline, update shortlist, generate email preview.

Usage:
    python3 preview.py                # full pipeline + preview (opens in browser)
    python3 preview.py --skip-search  # reuse latest data, just regenerate outputs
    python3 preview.py --top 15       # show top 15 in email (default: 10)

Outputs:
    email_preview.html      — email ready to copy-paste into Gmail
    docs/index.html         — updated shortlist page (push to GitHub Pages)
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "data" / "listings"


def latest_results():
    """Load most recent search results JSON."""
    files = sorted(RESULTS_DIR.glob("search_*.json"), reverse=True)
    if not files:
        return None, None
    with open(files[0]) as f:
        data = json.load(f)
    return data, files[0].name


def run_pipeline():
    """Run search.py and return exit code."""
    print("=" * 60)
    print("RUNNING PIPELINE")
    print("=" * 60)
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "search.py")],
        cwd=str(BASE_DIR),
    )
    return result.returncode


def update_shortlist(properties):
    """Regenerate the GitHub Pages shortlist."""
    print("\n" + "=" * 60)
    print("UPDATING SHORTLIST PAGE")
    print("=" * 60)
    try:
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "shortlist.py")],
            cwd=str(BASE_DIR),
        )
        if result.returncode == 0:
            print("Shortlist page updated → docs/index.html")
        return result.returncode == 0
    except Exception as e:
        print(f"Shortlist update failed: {e}")
        return False


def generate_email_preview(properties, search_date, top_n=20, card_count=10):
    """Generate both email formats and save previews."""
    from email_template import render_email
    from email_sender import _build_link_email

    shortlist_url = os.getenv("SHORTLIST_URL", "https://karl-reforged.github.io/edm-shortlist/")

    # Sort by score descending, filter out sold/under offer
    _sold_words = ("sold", "deposit taken", "under offer", "under contract")
    sorted_props = sorted(
        [p for p in properties
         if not any(w in (p.get("display_price", "") or "").lower() for w in _sold_words)],
        key=lambda p: p.get("score", {}).get("pct", 0),
        reverse=True,
    )

    # ── Full card email (for manual send / copy-paste) ──
    top_props = sorted_props[:top_n]
    full_html = render_email(top_props, search_date=search_date, card_count=card_count)

    # Wire up feedback placeholder URLs
    # Until the Google Apps Script is deployed, use the shortlist URL as base
    feedback_base = os.getenv("FEEDBACK_SCRIPT_URL", "")
    if feedback_base:
        for i, prop in enumerate(top_props):
            sid = prop.get("source_id", str(i))
            for reaction in ["LOVE", "INTERESTING", "NO"]:
                placeholder = f"FEEDBACK_URL_{reaction}_{i}"
                real_url = f"{feedback_base}?reaction={reaction.lower()}&property={sid}"
                full_html = full_html.replace(placeholder, real_url)
    else:
        # No feedback URL — link buttons to the listing page instead
        for i, prop in enumerate(top_props):
            listing_url = prop.get("listing_url", "#")
            for reaction in ["LOVE", "INTERESTING", "NO"]:
                placeholder = f"FEEDBACK_URL_{reaction}_{i}"
                full_html = full_html.replace(placeholder, listing_url)

    full_preview = BASE_DIR / "email_preview.html"
    with open(full_preview, "w") as f:
        f.write(full_html)

    # ── Link email (for Resend / clean send) ──
    plain, link_html = _build_link_email(sorted_props, search_date, shortlist_url)
    link_preview = BASE_DIR / "email_link_preview.html"
    with open(link_preview, "w") as f:
        f.write(link_html)

    return full_preview, link_preview, sorted_props[:top_n]


def print_summary(properties, top_n=10):
    """Print a quick audit summary."""
    _sold_words = ("sold", "deposit taken", "under offer", "under contract")
    sorted_props = sorted(
        [p for p in properties
         if not any(w in (p.get("display_price", "") or "").lower() for w in _sold_words)],
        key=lambda p: p.get("score", {}).get("pct", 0),
        reverse=True,
    )

    print("\n" + "=" * 60)
    print(f"SHORTLIST SUMMARY — {len(properties)} properties")
    print("=" * 60)

    # Score distribution
    scores = [p["score"]["pct"] for p in properties]
    print(f"\nScore range: {min(scores):.0f}% – {max(scores):.0f}%")
    for lo, hi in [(80, 100), (70, 79), (60, 69), (50, 59)]:
        c = sum(1 for s in scores if lo <= s <= hi)
        if c:
            print(f"  {lo}-{hi}%: {c} properties")

    # Top N for the email
    print(f"\n{'─' * 60}")
    print(f"TOP {top_n} FOR GEORGE'S EMAIL")
    print(f"{'─' * 60}")
    for i, p in enumerate(sorted_props[:top_n], 1):
        pct = p["score"]["pct"]
        price = p.get("display_price", "?")[:16]
        acres = f"{p['land_acres']:.0f}ac" if p.get("land_acres") else "?"
        suburb = p.get("suburb", "")[:15]
        hl = p.get("headline", "")[:35]
        drive = ""
        if p.get("drive_time_minutes"):
            h = int(p["drive_time_minutes"] // 60)
            m = int(p["drive_time_minutes"] % 60)
            drive = f"{h}h{m:02d}"
        print(f"  {i:2d}. {pct:4.0f}%  {price:>16s}  {acres:>6s}  {drive:>5s}  {suburb:15s}  {hl}")

    # Potential concerns
    top = sorted_props[:top_n]
    no_price = sum(1 for p in top if not p.get("price"))
    no_desc = sum(1 for p in top if not p.get("description") or len(p.get("description", "")) < 50)
    sold = sum(1 for p in top if any(w in (p.get("display_price", "") or "").lower() for w in ["sold", "deposit taken", "under offer"]))

    if no_price or no_desc or sold:
        print(f"\n⚠ Flags in top {top_n}:")
        if no_price:
            print(f"  {no_price} without numeric price (Contact Agent etc)")
        if no_desc:
            print(f"  {no_desc} with thin/missing description")
        if sold:
            print(f"  {sold} may be sold/under offer")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Weekly preview workflow")
    parser.add_argument("--skip-search", action="store_true", help="Reuse latest data")
    parser.add_argument("--top", type=int, default=20, help="Top N properties for email")
    parser.add_argument("--cards", type=int, default=10, help="Full photo cards (rest shown as table)")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    # 1. Run pipeline (unless skipped)
    if not args.skip_search:
        rc = run_pipeline()
        if rc != 0:
            print(f"\nPipeline failed (exit {rc}). Fix errors and retry.")
            sys.exit(1)

    # 2. Load results
    data, filename = latest_results()
    if not data:
        print("No search results found. Run the pipeline first.")
        sys.exit(1)

    properties = data.get("properties", [])
    search_date = datetime.now().strftime("%d %B %Y")
    print(f"\nLoaded {len(properties)} properties from {filename}")

    # 3. Print summary
    print_summary(properties, top_n=args.top)

    # 4. Update shortlist page
    update_shortlist(properties)

    # 5. Generate email previews
    print("\n" + "=" * 60)
    print("GENERATING EMAIL PREVIEWS")
    print("=" * 60)
    full_preview, link_preview, top_props = generate_email_preview(
        properties, search_date, top_n=args.top, card_count=args.cards
    )
    print(f"\n  Full card email → {full_preview.name}")
    print(f"  Link email      → {link_preview.name}")
    print(f"  Properties shown: {len(top_props)}")

    # 6. Open in browser
    if not args.no_open:
        print(f"\nOpening email preview...")
        subprocess.run(["open", str(full_preview)])

    # 7. Next steps
    print(f"\n{'=' * 60}")
    print("READY TO SEND")
    print(f"{'=' * 60}")
    print(f"""
To send to George this weekend:

  Option A — Copy-paste the card email:
    1. Open email_preview.html in browser (already opened)
    2. Select All → Copy
    3. Paste into Gmail compose → Send to George

  Option B — Send the link email (shorter, points to shortlist):
    1. Open email_link_preview.html
    2. Copy-paste into Gmail, OR
    3. Run email_sender.py (Resend integration, requires RESEND_API_KEY in .env)

  Don't forget to push the shortlist:
    git add docs/ && git commit -m "Update shortlist" && git push
""")


if __name__ == "__main__":
    main()
