import os
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from email_template import render_email
from email_sender import _build_link_email
from shortlist import _fetch_sheet_properties, _visible_props


ROOT = Path(__file__).resolve().parents[1]
LIVE_SHORTLIST_URL = "https://karl-reforged.github.io/bolt-hole/"


class SiteIntegrityTests(unittest.TestCase):
    def test_incomplete_listingloop_property_is_not_published_as_a_normal_card(self):
        incomplete = {
            "source": "listing_loop",
            "source_id": "ll_incomplete",
            "suburb": "Tapitallee",
            "postcode": "2540",
            "listing_url": "https://buyer.listingloop.com.au/buyer/#/properties/incomplete",
            "price": None,
            "land_acres": None,
            "bedrooms": None,
        }

        self.assertEqual(_visible_props([incomplete]), [])

    def test_enriched_listingloop_property_can_be_published(self):
        enriched = {
            "source": "listing_loop",
            "source_id": "ll_enriched",
            "address": "12 Example Road",
            "suburb": "Tapitallee",
            "postcode": "2540",
            "listing_url": "https://buyer.listingloop.com.au/buyer/#/properties/enriched",
            "price": 900_000,
        }

        self.assertEqual([p["source_id"] for p in _visible_props([enriched])], ["ll_enriched"])

    def test_database_overlay_uses_an_explicit_application_identity(self):
        body = json.dumps({"properties": [{"source_id": "archived-1"}]}).encode()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return body

        with patch("urllib.request.urlopen", return_value=Response()) as open_url:
            properties = _fetch_sheet_properties()

        request = open_url.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), "bolt-hole-shortlist/1.0")
        self.assertIn("archived-1", properties)

    def test_email_fallback_links_to_the_live_shortlist(self):
        with patch.dict(os.environ, {}, clear=True):
            html = render_email([], search_date="17 August 2026")

            self.assertIn(LIVE_SHORTLIST_URL, html)

    def test_email_preview_excludes_archived_properties(self):
        properties = [
            {
                "source_id": "offer",
                "suburb": "Old Place",
                "display_price": "UNDER OFFER",
                "land_acres": 40,
                "score": {"pct": 99},
            },
            {
                "source_id": "active",
                "suburb": "Available Place",
                "price": 1_200_000,
                "land_acres": 50,
                "score": {"pct": 80},
            },
        ]
        plain, html = _build_link_email(properties, "17 August 2026", LIVE_SHORTLIST_URL)
        self.assertIn("1 properties this week", plain)
        self.assertIn("Available Place", plain)
        self.assertNotIn("Old Place", plain)
        self.assertNotIn("UNDER OFFER", html)
        self.assertNotIn("/edm-shortlist/", html)

    def test_market_map_popup_does_not_render_missing_summary_quartiles(self):
        html = (ROOT / "docs" / "dashboard.html").read_text()

        self.assertNotIn("fmtK(s.p25)", html)
        self.assertNotIn("fmtK(s.p75)", html)

    def test_market_map_has_a_phone_layout(self):
        html = (ROOT / "docs" / "dashboard.html").read_text()

        self.assertIn("@media (max-width: 720px)", html)
        self.assertIn("flex-direction: column", html)
        self.assertIn("height: 52vh", html)

    def test_shortlist_phone_controls_wrap_and_have_touch_sized_targets(self):
        html = (ROOT / "docs" / "index.html").read_text()

        self.assertIn(".sort-bar { flex-wrap: wrap; overflow-x: visible; }", html)
        self.assertIn(".sort-btn { min-height: 44px; }", html)
        self.assertIn(".feedback .btn, .notes-pill { min-height: 44px; }", html)
        self.assertIn("body > nav::after", html)

    def test_shortlist_feedback_controls_expose_state_to_assistive_technology(self):
        html = (ROOT / "docs" / "index.html").read_text()

        self.assertIn('aria-label="Add a note for this property"', html)
        self.assertIn('role="status" aria-live="polite"', html)
        self.assertIn('aria-pressed="false"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn("btn.setAttribute('aria-pressed'", html)
        self.assertIn("pill.setAttribute('aria-expanded'", html)

    def test_market_map_controls_are_keyboard_accessible(self):
        html = (ROOT / "docs" / "dashboard.html").read_text()

        self.assertNotIn('<div class="map-toggle', html)
        self.assertIn('<button type="button" class="map-toggle', html)
        self.assertIn("'<button type=\"button\" class=\"corridor-card\"", html)

    def test_market_map_phone_can_collapse_legend_and_return_to_map(self):
        html = (ROOT / "docs" / "dashboard.html").read_text()

        self.assertIn('class="map-legend-toggle"', html)
        self.assertIn('aria-controls="map-legend"', html)
        self.assertIn(".map-legend:not(.open) { display: none; }", html)
        self.assertIn('class="detail-map-button"', html)
        self.assertIn("function showSelectedCorridorOnMap()", html)

    def test_historical_page_links_back_to_the_current_shortlist(self):
        html = (ROOT / "docs" / "top10.html").read_text()

        self.assertIn('<a href="./">current Shortlist</a>', html)


if __name__ == "__main__":
    unittest.main()
