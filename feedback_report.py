#!/usr/bin/env python3
"""Export attributed feedback into a private, reviewable analysis summary."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from secret_store import get_admin_token

load_dotenv()

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "data" / "feedback" / "latest_summary.json"
REACTION_WEIGHTS = {"love": 2, "interesting": 1, "pass": -2}
FAVOURITE_WEIGHT = 2


def build_feedback_summary(export: dict, generated_at: str | None = None) -> dict:
    """Turn a raw database export into counts and tag signals for human review."""
    properties = {
        str(row.get("source_id")): row
        for row in export.get("properties", [])
        if row.get("source_id")
    }
    participant_counts: dict[str, dict] = defaultdict(
        lambda: {"notes": 0, "reactions": Counter(), "favourites": 0}
    )
    overall: dict[str, dict] = defaultdict(lambda: {"events": 0, "score": 0})
    by_author: dict[str, dict[str, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"events": 0, "score": 0})
    )
    unmatched = 0

    notes = []
    for note in export.get("notes", []):
        author = str(note.get("author") or "Anonymous")
        participant_counts[author]["notes"] += 1
        notes.append({
            "id": note.get("id"),
            "property_id": note.get("property_id"),
            "author": author,
            "timestamp": note.get("timestamp"),
            "note": note.get("note", ""),
        })

    events = []
    for reaction in export.get("reactions", []):
        author = str(reaction.get("author") or "Anonymous")
        kind = str(reaction.get("reaction") or "")
        participant_counts[author]["reactions"][kind] += 1
        if kind in REACTION_WEIGHTS:
            events.append((reaction.get("property_id"), author, REACTION_WEIGHTS[kind]))
    for favourite in export.get("favourites", []):
        author = str(favourite.get("author") or "Anonymous")
        participant_counts[author]["favourites"] += 1
        events.append((favourite.get("property_id"), author, FAVOURITE_WEIGHT))

    for property_id, author, weight in events:
        prop = properties.get(str(property_id))
        if not prop:
            unmatched += 1
            continue
        payload = prop.get("payload") if isinstance(prop.get("payload"), dict) else {}
        tags = payload.get("tags", []) if isinstance(payload, dict) else []
        for tag in {str(tag) for tag in tags if tag}:
            overall[tag]["events"] += 1
            overall[tag]["score"] += weight
            by_author[author][tag]["events"] += 1
            by_author[author][tag]["score"] += weight

    participants = {}
    for author, counts in sorted(participant_counts.items()):
        participants[author] = {
            "notes": counts["notes"],
            "reactions": dict(sorted(counts["reactions"].items())),
            "favourites": counts["favourites"],
        }

    return {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "purpose": "Review input only; this file does not automatically change scoring criteria.",
        "participants": participants,
        "signals": {
            "overall": dict(sorted(overall.items())),
            "by_author": {
                author: dict(sorted(tags.items()))
                for author, tags in sorted(by_author.items())
            },
        },
        "unmatched_feedback_events": unmatched,
        "notes": notes,
    }


def fetch_feedback_export(endpoint: str, admin_token: str) -> dict:
    if not endpoint or not admin_token:
        raise RuntimeError("NOTES_SCRIPT_URL and BOLT_ADMIN_TOKEN are required")
    separator = "&" if "?" in endpoint else "?"
    response = requests.get(
        f"{endpoint}{separator}action=feedback_export",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if not all(isinstance(data.get(key), list) for key in ("properties", "notes", "reactions", "favourites")):
        raise RuntimeError("Feedback export response is incomplete")
    return data


def write_summary(summary: dict, output: Path = DEFAULT_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=output.parent, delete=False) as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(output)
    return output


def main() -> int:
    endpoint = os.getenv("NOTES_SCRIPT_URL", "https://bolt-hole-backend.karl-582.workers.dev")
    token = get_admin_token()
    summary = build_feedback_summary(fetch_feedback_export(endpoint, token))
    output = write_summary(summary)
    print(f"Feedback analysis saved privately: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
