import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"a", "link"} and values.get("href"):
            self.links.append(values["href"])
        if tag in {"img", "script"} and values.get("src"):
            self.links.append(values["src"])


class GeneratedLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (DOCS / "index.html").read_text()

    def test_every_property_card_has_a_unique_id_and_https_listing(self):
        cards = re.findall(
            r'<div class="card"[^>]*data-property-id="([^"]+)".*?'
            r'<a href="([^"]*)"[^>]*class="btn btn-view"',
            self.html,
            re.DOTALL,
        )
        self.assertGreater(len(cards), 100)
        ids = [property_id for property_id, _ in cards]
        self.assertEqual(len(ids), len(set(ids)))
        for property_id, url in cards:
            with self.subTest(property_id=property_id):
                parsed = urlparse(url)
                self.assertEqual(parsed.scheme, "https")
                self.assertTrue(parsed.netloc)
                if parsed.netloc == "www.domain.com.au":
                    self.assertIn(property_id, parsed.path,
                                  "Domain link does not belong to the displayed property")
                elif property_id.startswith("elders-"):
                    self.assertIn(property_id.removeprefix("elders-").lower(), parsed.path.lower())
                elif property_id.startswith("ll_"):
                    compact_url = (parsed.path + parsed.fragment).replace("-", "").lower()
                    self.assertIn(property_id.removeprefix("ll_").replace("-", "").lower(), compact_url)
                elif property_id.startswith("cre_"):
                    _, postcode, slug = property_id.split("_", 2)
                    compact_path = re.sub(r"[^a-z0-9]", "", parsed.path.lower())
                    self.assertIn(postcode, compact_path)
                    self.assertIn(slug, compact_path)
        self.assertNotIn("www.commercialrealestate.com.au", self.html)

    def test_internal_navigation_targets_exist(self):
        parser = LinkCollector()
        parser.feed(self.html)
        for link in parser.links:
            parsed = urlparse(link)
            if parsed.scheme or link.startswith(("#", "mailto:", "tel:")):
                continue
            target = parsed.path
            if not target or target == "./":
                target = "index.html"
            with self.subTest(link=link):
                self.assertTrue((DOCS / target).exists(), f"missing internal target: {link}")

    def test_every_published_page_has_valid_internal_links(self):
        for page in DOCS.glob("*.html"):
            parser = LinkCollector()
            parser.feed(page.read_text())
            for link in parser.links:
                parsed = urlparse(link)
                if parsed.scheme or parsed.netloc or link.startswith(("#", "mailto:", "tel:")):
                    continue
                target = parsed.path
                if not target or target == "./":
                    target = "index.html"
                with self.subTest(page=page.name, link=link):
                    self.assertTrue(
                        (page.parent / target).resolve().is_file(),
                        f"{page.name} points to missing internal target: {link}",
                    )

    def test_published_pages_reserve_image_space_and_use_semantic_controls(self):
        for page in DOCS.glob("*.html"):
            source = page.read_text()
            with self.subTest(page=page.name):
                self.assertNotRegex(source, r'<(?:div|span)[^>]+onclick=')
                self.assertNotIn("transition: all", source)
                for image in re.findall(r"<img\b([^>]*)>", source):
                    self.assertIn("width=", image)
                    self.assertIn("height=", image)

    def test_property_photos_reserve_space_before_loading(self):
        photos = re.findall(r'<div class="card-photo"><img ([^>]+)>', self.html)
        self.assertGreater(len(photos), 100)
        for attrs in photos:
            self.assertIn('width="720"', attrs)
            self.assertIn('height="540"', attrs)
        self.assertIn("height: clamp(180px, 40vw, 240px)", self.html)

    def test_property_photos_avoid_known_stale_supplier_urls(self):
        self.assertNotIn("elders-re-vre-cdn.imgix.net", self.html)
        self.assertNotIn("farmbuycdn.clodflare.pushcreative.com.au", self.html)
        self.assertNotRegex(
            self.html,
            r'src="https://i\d+\.au\.reastatic\.net/\d+x\d+-fit"',
        )
        self.assertNotRegex(
            self.html,
            r'farmbuycdn\.edge\.pushcreative\.com\.au/[^"?]+/512_',
        )

    def test_brayton_rea_listing_uses_its_complete_photo_url(self):
        card = re.search(
            r'<div class="card[^>]+data-property-id="rea-149223908".*?</div>\s*</div>',
            self.html,
            re.DOTALL,
        ).group(0)
        self.assertIn("1200x900-fit,format=webp/", card)
        self.assertIn("/image.png", card)

    def test_farmbuy_photos_use_the_browser_safe_relay(self):
        self.assertIn("?action=photo&url=", self.html)
        self.assertIn("encodeURIComponent(image.src)", self.html)

    def test_map_and_card_navigation_uses_keyboard_controls(self):
        self.assertNotIn('<span class="rank-badge"', self.html)
        self.assertIn('<button type="button" class="rank-badge"', self.html)
        self.assertIn('aria-label="Selected property"', self.html)
        self.assertIn("wireMarkerAccessibility(marker, m,", self.html)

    def test_dense_property_map_uses_clusters(self):
        self.assertIn("L.markerClusterGroup", self.html)
        self.assertIn("zoomToShowLayer", self.html)
        self.assertIn('class="property-cluster"', self.html)
        self.assertIn("restoreMapPinState(m.idx, m.pct, el)", self.html)

    def test_map_pins_open_adaptive_previews_before_full_details(self):
        self.assertIn('id="map-preview-inline"', self.html)
        self.assertIn('id="map-preview-expanded"', self.html)
        self.assertIn('class="map-modal-body"', self.html)
        self.assertIn("showMapPreview(m.idx, 'inline')", self.html)
        self.assertIn("showMapPreview(m.idx, 'expanded')", self.html)
        self.assertIn("function viewMapPreviewDetails(idx, context)", self.html)
        self.assertIn('>View full details</button>', self.html)
        self.assertIn('>View listing &nearr;</a>', self.html)
        self.assertIn('class="map-preview-grip"', self.html)
        self.assertIn("function toggleMapPreviewSheet(button)", self.html)
        self.assertIn(".map-preview:not(.is-expanded) .map-preview-stats", self.html)
        self.assertIn("@media (max-width: 1024px)", self.html)
        self.assertIn('data-context="inline"', self.html)
        self.assertIn('data-context="expanded"', self.html)
        self.assertIn("mapPreviewSelection[pin.dataset.context]", self.html)
        self.assertNotIn('class="popup-link"', self.html)
        self.assertNotIn("marker.openPopup()", self.html)

    def test_unavailable_properties_have_a_separate_past_listings_view(self):
        self.assertIn('class="past-listings-link" href="?view=past"', self.html)
        self.assertIn('<strong>Past Listings</strong>', self.html)
        self.assertIn('no longer available', self.html)
        self.assertIn('class="past-summary"', self.html)
        self.assertIn('class="card archived-card"', self.html)
        self.assertIn('class="availability-badge">Under offer</span>', self.html)
        self.assertIn("document.documentElement.classList.add('past-view')", self.html)
        self.assertIn("html.past-view .dismissed-divider", self.html)
        self.assertNotIn('archived-rank', self.html)

    def test_feedback_actions_ask_for_identity_only_when_the_user_first_saves(self):
        self.assertIn('id="identity-dialog"', self.html)
        self.assertIn("Who's reviewing?", self.html)
        self.assertIn('Continue anonymously', self.html)
        self.assertIn('id="feedback-access" hidden', self.html)
        self.assertIn('.feedback-access[hidden] { display: none; }', self.html)
        self.assertEqual(
            self.html.count('if (!await ensureFeedbackIdentity()) return;'),
            3,
        )

    def test_anonymous_copy_distinguishes_private_feedback_from_shared_notes(self):
        self.assertIn('Reactions and saved properties stay on this device.', self.html)
        self.assertIn('Notes are shared as Anonymous.', self.html)
        self.assertNotIn('feedback stays on this device', self.html)

    def test_shortlist_is_organised_by_the_users_review_task(self):
        self.assertRegex(self.html, r'data-view="review"[^>]*>To Review')
        self.assertRegex(self.html, r'data-view="saved"[^>]*>Saved')
        self.assertRegex(self.html, r'data-view="all"[^>]*>All Available')
        task_views = re.search(
            r'<div class="task-views"[^>]*>(.*?)</div>',
            self.html,
            re.DOTALL,
        ).group(1)
        self.assertEqual(task_views.count('data-view='), 3)
        self.assertNotIn('Past Listings', task_views)
        self.assertIn('class="past-listings-link" href="?view=past"', self.html)
        self.assertIn('grid-template-columns: repeat(3, 1fr)', self.html)
        self.assertNotIn('.task-views { grid-template-columns: 1fr 1fr; }', self.html)
        self.assertIn('background: #EDEBE7', self.html)
        self.assertIn('border-bottom: 1px solid #E2DDD6', self.html)
        self.assertRegex(self.html, r'\.task-view-count \{[^}]*font-size: 13px')
        self.assertIn('.task-views button { padding-inline: 4px; }', self.html)
        self.assertIn("function applyTaskView()", self.html)
        self.assertIn("classList.remove('past-view')", self.html)
        self.assertIn("const ANONYMOUS_NOTE_REVIEW_KEY", self.html)
        self.assertIn("const hasNamedNote = Boolean(feedbackIdentity.author)", self.html)
        self.assertIn("const hasAnonymousNote = !feedbackIdentity.author", self.html)
        self.assertIn("state.anonymousNoteReviews[propertyId]", self.html)
        self.assertIn("const hasNote = hasNamedNote || hasAnonymousNote;", self.html)
        self.assertIn("const needsReview = !reaction && !favourite && !hasNote;", self.html)

    def test_shortlist_uses_simple_copy_and_a_collapsible_mobile_map(self):
        self.assertIn('<title>Bolt Hole — Property Shortlist</title>', self.html)
        self.assertIn('<h1>Bolt Hole &mdash; Property Shortlist</h1>', self.html)
        self.assertIn('class="freshness">Updated ', self.html)
        self.assertNotIn('class="scrape-status"', self.html)
        self.assertIn('class="map-mobile-toggle"', self.html)
        self.assertIn('function toggleInlineMap()', self.html)
        self.assertNotIn("html:not(.task-view-all):not(.past-view) .map-container", self.html)

    def test_global_navigation_uses_three_customer_facing_destinations(self):
        for page_name in (
            "index.html",
            "dashboard.html",
            "bolt-hole-overview.html",
            "system-map.html",
        ):
            source = (DOCS / page_name).read_text()
            with self.subTest(page=page_name):
                self.assertIn('>Shortlist</a>', source)
                self.assertIn('>Area Insights</a>', source)
                self.assertIn('>About the Search</a>', source)
                self.assertNotIn('>Market Map</a>', source)
                self.assertNotIn('>How It Works</a>', source)


if __name__ == "__main__":
    unittest.main()
