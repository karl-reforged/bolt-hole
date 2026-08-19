#!/usr/bin/env python3
"""Canonical public-site state and coherence verification for Bolt Hole."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
STATE_PATH = DOCS_DIR / "site-state.json"
PUBLIC_PAGES = (
    DOCS_DIR / "index.html",
    DOCS_DIR / "bolt-hole-overview.html",
    DOCS_DIR / "system-map.html",
    DOCS_DIR / "dashboard.html",
)


def _score_pct(prop: dict) -> float:
    score = prop.get("score") or {}
    try:
        return float(score.get("pct") or 0)
    except (TypeError, ValueError):
        return 0.0


def build_site_state(
    active_props: list[dict],
    archived_props: list[dict],
    *,
    search_display: str,
    run_metadata: dict | None = None,
    published_at: datetime | None = None,
) -> dict:
    """Build the one public state object consumed by every site page."""
    run_metadata = run_metadata or {}
    published_at = published_at or datetime.now().astimezone()
    active_sources = Counter(
        str(prop.get("source") or "unknown") for prop in active_props
    )
    scores = [_score_pct(prop) for prop in active_props]
    scores = [score for score in scores if score > 0]
    top = max(active_props, key=_score_pct, default={})
    source_report = run_metadata.get("source_report") or {}
    scanned = sum(
        int(report.get("count") or 0)
        for report in source_report.values()
        if isinstance(report, dict)
    )
    source_failures = [
        name
        for name, report in source_report.items()
        if isinstance(report, dict) and report.get("error")
    ]
    automated_feed_count = sum(
        bool(report.get("count"))
        for name, report in source_report.items()
        if isinstance(report, dict)
        and name not in {"Domain API", "REA Manual"}
        and not report.get("error")
    )
    passed_gates = int(run_metadata.get("passed_gates") or len(active_props))

    return {
        "schema_version": 1,
        "published_at": published_at.isoformat(timespec="seconds"),
        "search_at": run_metadata.get("search_date"),
        "search_display": search_display,
        "inventory": {
            "available": len(active_props),
            "archived": len(archived_props),
            "possibly_unavailable": sum(
                prop.get("status") == "possibly_unavailable" for prop in active_props
            ),
            "under_offer": sum(
                prop.get("status") == "under_offer" for prop in archived_props
            ),
            "sources": dict(sorted(active_sources.items())),
            "source_count": len(active_sources),
            "automated_feed_count": automated_feed_count,
        },
        "run": {
            "scanned": scanned,
            "passed_gates": passed_gates,
            "pass_rate": round((passed_gates / scanned * 100), 1) if scanned else None,
            "source_failures": source_failures,
        },
        "scores": {
            "minimum": round(min(scores), 1) if scores else None,
            "maximum": round(max(scores), 1) if scores else None,
        },
        "top_match": {
            "source_id": str(top.get("source_id") or top.get("id") or ""),
            "headline": top.get("headline") or top.get("address") or "",
            "address": top.get("address") or "",
            "score": round(_score_pct(top), 1) if top else None,
        },
        "market_data": {
            "sales": 1296,
            "source": "NSW PSI",
            "through": "December 2024",
        },
    }


def write_site_state(state: dict, path: Path = STATE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    return path


def verify_site_bundle(docs_dir: Path = DOCS_DIR) -> list[str]:
    """Return coherence errors; an empty list means the bundle is publishable."""
    errors: list[str] = []
    state_path = docs_dir / "site-state.json"
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError) as exc:
        return [f"site-state.json is unavailable or invalid: {exc}"]

    inventory = state.get("inventory") or {}
    available = inventory.get("available")
    archived = inventory.get("archived")
    search_display = state.get("search_display")
    if not isinstance(available, int) or available < 0:
        errors.append("site-state available count is invalid")
    if not isinstance(archived, int) or archived < 0:
        errors.append("site-state archived count is invalid")
    if not search_display:
        errors.append("site-state search_display is missing")

    pages = {
        "index.html": docs_dir / "index.html",
        "bolt-hole-overview.html": docs_dir / "bolt-hole-overview.html",
        "system-map.html": docs_dir / "system-map.html",
        "dashboard.html": docs_dir / "dashboard.html",
    }
    text_by_name: dict[str, str] = {}
    for name, path in pages.items():
        try:
            text = path.read_text()
        except OSError as exc:
            errors.append(f"{name} is unavailable: {exc}")
            continue
        text_by_name[name] = text
        if "site-state.js" not in text:
            errors.append(f"{name} does not consume site-state.js")

    index = text_by_name.get("index.html", "")
    available_match = re.search(r'Available \(<span[^>]*>(\d+)</span>\)', index)
    archived_match = re.search(r'Archived \(<span[^>]*>(\d+)</span>\)', index)
    if available_match and available_match.group(1) != str(available):
        errors.append(
            f"index available count {available_match.group(1)} != site-state {available}"
        )
    if archived_match and archived_match.group(1) != str(archived):
        errors.append(
            f"index archived count {archived_match.group(1)} != site-state {archived}"
        )
    if search_display and search_display not in index:
        errors.append("index publication date does not match site-state search_display")

    stale_claims = {
        "Last updated: 17 August 2026",
        "System status as of 4 May 2026",
        "Last updated: 24 April 2026",
        "137 available properties",
        "358 listings",
        "143 passing all gates",
        "370</div>",
        "167</div>",
        "163 pass",
        "163/163 enriched",
        "69&ndash;78% scores",
        "first automated email coming shortly",
        "Your first weekly email arrives soon",
    }
    for name, text in text_by_name.items():
        for claim in stale_claims:
            if claim in text:
                errors.append(f"{name} contains stale claim: {claim}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="verify docs bundle")
    args = parser.parse_args()
    if not args.verify:
        parser.error("use --verify")
    errors = verify_site_bundle()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Site bundle coherent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
