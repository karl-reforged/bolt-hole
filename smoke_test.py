#!/usr/bin/env python3
"""Offline smoke test for the Bolt Hole shortlist pipeline.

Verifies the pipeline is workable without a live scrape or network access:
  1. sources sheet-cache helper degrades to {} offline (never raises)
  2. union loader parses local scrape JSONs, dedupes by source_id
  3. suppression filter drops SUPPRESSED_SOURCES
  4. shortlist renders end-to-end to a temp file (docs/index.html untouched)

Run: .venv/bin/python smoke_test.py   (or python3 smoke_test.py)
Exits 0 on pass, 1 on failure. No dependencies beyond the repo's own.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "data" / "listings"

# Force offline behaviour: empty NOTES_SCRIPT_URL makes every sheet fetch
# return {} instead of hitting the network. Must be set before imports.
os.environ["NOTES_SCRIPT_URL"] = ""
os.environ.setdefault("BOLT_SKIP_SHEET_UPSERT", "1")

PASS, FAIL = 0, 0


def check(label, ok, detail=""):
    global PASS, FAIL
    mark = "ok" if ok else "FAIL"
    print(f"  [{mark:>4}] {label}" + (f" — {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1


def main():
    print("Bolt Hole smoke test (offline)\n")

    # ── 1. Sheet cache degrades gracefully offline ──
    from sources import _load_sheet_description_cache
    import sources
    orig_url = sources.SHEET_DB_URL
    sources.SHEET_DB_URL = ""  # simulate no endpoint
    try:
        cache = _load_sheet_description_cache()
        check("sheet description cache returns {} offline", cache == {})
    finally:
        sources.SHEET_DB_URL = orig_url

    # ── 2. Union loader over local scrape JSONs ──
    import shortlist

    have_jsons = bool(sorted(RESULTS_DIR.glob("search_*.json")))
    if not have_jsons:
        print("  [skip] no local search_*.json files — union/render checks skipped")
        return summary()

    union_props, latest_file = shortlist._load_union_of_runs()
    check("union loader runs and finds latest file", latest_file is not None,
          latest_file.name if latest_file else "")
    if not union_props or not shortlist._visible_props(union_props):
        print(f"  [info] union yields {len(union_props)} visible properties — "
              "all listings past the 21-day age-out; run a fresh scrape before publishing")

    # Deterministic checks run on the latest scrape's raw properties, so the
    # test doesn't fail merely because the data is old.
    with open(latest_file) as fh:
        props = json.load(fh).get("properties", [])
    check("latest scrape has a healthy property count", len(props) >= 100,
          f"{len(props)} properties in {latest_file.name}")

    sids = [p.get("source_id") for p in props if p.get("source_id")]
    check("no duplicate source_ids", len(sids) == len(set(sids)),
          f"{len(sids) - len(set(sids))} dupes" if len(sids) != len(set(sids)) else "")

    addresses = [str(p.get("address") or "").strip().lower() for p in props]
    addresses = [a for a in addresses if a]
    dupes = len(addresses) - len(set(addresses))
    check("duplicate addresses within tolerance", dupes <= 3, f"{dupes} shared addresses")

    # ── 3. Suppression filter ──
    visible = shortlist._visible_props(props)
    leaked = [p for p in visible if p.get("source") in shortlist.SUPPRESSED_SOURCES]
    check("suppressed sources filtered", not leaked,
          f"{len(leaked)} leaked" if leaked else f"{len(props) - len(visible)} suppressed")

    # ── 4. End-to-end render to a temp file ──
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        shortlist.generate_shortlist(props, output_path=tmp_path)
        html = tmp_path.read_text()
        check("render produces substantial HTML", len(html) > 100_000, f"{len(html):,} bytes")
        card_count = html.count('<div class="card" id="card-')
        check("render contains one card per visible property", card_count == len(visible),
              f"{card_count} cards for {len(visible)} visible properties")
        check("render wires reactions loader", "loadServerReactions" in html)
        expected_people = ["George", "Mary", "Alex", "Greg", "Justin"]
        check("known people are offered on the first feedback action",
              '<dialog class="identity-dialog" id="identity-dialog"' in html
              and "Who's reviewing?" in html
              and all(f"chooseFeedbackIdentity('{name}')" in html
                      for name in expected_people)
              and "chooseFeedbackIdentity('')" in html
              and "ensureFeedbackIdentity" in html)
        check("cross-device behaviour is explained",
              "across devices" in html and "this browser" in html)
        check("stale identity reads and writes are discarded",
              "feedbackIdentity.version" in html
              and html.count("identityVersionIsCurrent(version)") >= 5)
        check("notes use idempotent confirmed writes",
              "idempotency_key" in html and "response.ok" in html)
        check("note double-submits are blocked",
              "pendingNoteSaves" in html and "button.disabled" in html)
        check("favourites sync to the shared backend",
              "action: 'favourite'" in html)
        check("notes display their attributed author",
              '<span class="note-author">' in html)
        check("access tokens are never embedded in generated HTML",
              "SHORTLIST_ACCESS_TOKEN" not in html)
    finally:
        tmp_path.unlink(missing_ok=True)

    return summary()


def summary():
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
