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


if __name__ == "__main__":
    unittest.main()
