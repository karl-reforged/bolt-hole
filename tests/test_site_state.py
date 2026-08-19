import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from shortlist import _partition_props
from site_state import build_site_state, verify_site_bundle, write_site_state


class SiteStateTests(unittest.TestCase):
    def test_cross_source_duplicates_publish_as_one_active_property(self):
        properties = [
            {
                "source": "elders",
                "source_id": "elders-1",
                "address": "251 Sheepstation Forest Road, Gingkin NSW 2787",
                "status": "possibly_unavailable",
                "listing_url": "https://elders.example/1",
                "score": {"pct": 70},
            },
            {
                "source": "domain_web",
                "source_id": "domain-1",
                "address": "251 Sheepstation Forest Road Gingkin NSW 2787",
                "status": "active",
                "listing_url": "https://domain.example/1",
                "description": "Complete current listing",
                "score": {"pct": 72},
            },
        ]

        active, archived, total = _partition_props(properties)

        self.assertEqual(total, 1)
        self.assertEqual(archived, [])
        self.assertEqual(active[0]["source_id"], "domain-1")

    def test_same_source_properties_are_not_merged_only_because_address_matches(self):
        properties = [
            {
                "source": "domain_web",
                "source_id": "domain-1",
                "address": "Lot 1 Example Road Testville NSW 2000",
            },
            {
                "source": "domain_web",
                "source_id": "domain-2",
                "address": "Lot 1 Example Road Testville NSW 2000",
            },
        ]

        active, _, total = _partition_props(properties)

        self.assertEqual(total, 2)
        self.assertEqual(len(active), 2)

    def test_state_distinguishes_run_counts_from_published_inventory(self):
        active = [
            {
                "source": "domain_web",
                "source_id": "one",
                "headline": "Current property",
                "status": "active",
                "score": {"pct": 84},
            },
            {
                "source": "elders",
                "source_id": "two",
                "status": "possibly_unavailable",
                "score": {"pct": 63},
            },
        ]
        archived = [{"source_id": "old", "status": "archived"}]
        state = build_site_state(
            active,
            archived,
            search_display="19 August 2026 · 9:00am",
            run_metadata={
                "search_date": "2026-08-19T09:00:00+10:00",
                "passed_gates": 143,
                "source_report": {
                    "Domain Web": {"count": 300, "error": None},
                    "Elders": {"count": 20, "error": None},
                },
            },
            published_at=datetime(2026, 8, 19, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(state["inventory"]["available"], 2)
        self.assertEqual(state["inventory"]["archived"], 1)
        self.assertEqual(state["inventory"]["possibly_unavailable"], 1)
        self.assertEqual(state["run"]["scanned"], 320)
        self.assertEqual(state["run"]["passed_gates"], 143)
        self.assertEqual(state["top_match"]["headline"], "Current property")

    def test_bundle_verifier_rejects_page_count_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            state = build_site_state(
                [{"source": "domain_web", "score": {"pct": 80}}],
                [],
                search_display="19 August 2026",
            )
            write_site_state(state, docs / "site-state.json")
            (docs / "index.html").write_text(
                '<script src="site-state.js"></script>19 August 2026 '
                'Available (<span data-state="available">2</span>) '
                'Archived (<span data-state="archived">0</span>)'
            )
            for name in (
                "bolt-hole-overview.html",
                "system-map.html",
                "dashboard.html",
            ):
                (docs / name).write_text('<script src="site-state.js"></script>')

            errors = verify_site_bundle(docs)

        self.assertTrue(any("index available count 2" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
