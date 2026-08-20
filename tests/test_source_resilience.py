import json
import os
import importlib.util
import unittest
from unittest.mock import Mock, patch

import sources


class SourceResilienceTests(unittest.TestCase):
    def test_elders_pdf_dependency_is_installed(self):
        self.assertIsNotNone(importlib.util.find_spec("pdfplumber"))

    def test_og_image_parser_decodes_source_urls(self):
        html = (
            '<meta property="og:image" '
            'content="https://images.example/property.jpg?w=1200&amp;fit=max" />'
        )

        self.assertEqual(
            sources._extract_og_image(html),
            "https://images.example/property.jpg?w=1200&fit=max",
        )

    def test_listing_photo_enrichment_replaces_stale_source_url(self):
        response = Mock(
            status_code=200,
            text='<meta property="og:image" content="https://images.example/live.jpg?v=2" />',
        )
        session = Mock()
        session.get.return_value = response
        listings = [{
            "source_id": "listing-1",
            "listing_url": "https://listings.example/1",
            "photo_url": "https://images.example/stale.jpg",
        }]

        enriched = sources._enrich_listing_photos(
            listings,
            lambda listing: listing["listing_url"],
            session=session,
        )

        self.assertEqual(enriched[0]["photo_url"], "https://images.example/live.jpg?v=2")
        session.get.assert_called_once_with(
            "https://listings.example/1",
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (property search tool)"},
        )

    def test_apify_token_is_sent_only_in_authorization_headers(self):
        session = Mock()
        started = Mock(status_code=201)
        started.json.return_value = {
            "data": {"id": "run-1", "defaultDatasetId": "dataset-1"}
        }
        finished = Mock(status_code=200)
        finished.json.return_value = {"data": {"status": "SUCCEEDED"}}
        dataset = Mock(status_code=200)
        dataset.json.return_value = []
        session.post.return_value = started
        session.get.side_effect = [finished, dataset]

        criteria = {
            "gates": {
                "geography": {
                    "postcodes_west": ["2787"],
                    "postcodes_south": ["2580"],
                },
                "budget": {"min_price": 100_000, "max_price": 2_000_000},
                "land_size": {"min_hectares": 12.14, "max_hectares": 80.94},
            }
        }

        with (
            patch.dict(
                os.environ,
                {
                    "APIFY_API_TOKEN": "private-apify-token",
                    "APIFY_REA_ACTOR": "one-api/realestate-com-au-scraper",
                    "APIFY_MAX_POSTCODES": "0",
                },
            ),
            patch.object(sources, "_retry_session", return_value=session),
            patch.object(sources.time, "sleep"),
        ):
            self.assertEqual(sources.fetch_rea_apify(criteria), [])

        auth = {"Authorization": "Bearer private-apify-token"}
        self.assertEqual(session.post.call_args.kwargs["headers"], auth)
        self.assertNotIn("token", session.post.call_args.kwargs["params"])
        for call in session.get.call_args_list:
            self.assertEqual(call.kwargs["headers"], auth)
            self.assertNotIn("token", call.kwargs["params"])

        actor_input = session.post.call_args.kwargs["json"]
        self.assertEqual(actor_input["search_inputs"], ["2787", "2580"])
        self.assertEqual(actor_input["searchType"], "For_Sale")
        self.assertEqual(actor_input["propertyType"], "House,Acreage,Rural")
        self.assertEqual(actor_input["priceRange"], "min:100000,max:2000000")
        self.assertEqual(actor_input["landSizeRange"], "min:121400,max:809400")
        self.assertFalse(actor_input["surroundingSuburbs"])
        self.assertEqual(actor_input["resultCount"], 200)

    def test_one_api_schema_normalizes_complete_rea_listing(self):
        raw = {
            "listing_id": "700414500",
            "url": "https://www.realestate.com.au/property-farmlet-nsw-chatham+valley-700414500",
            "title": "FROG HOLLOW - 37 ACRES",
            "description": "Frog Hollow<br/>A useful rural description.",
            "price": "$750,000",
            "beds": 2,
            "baths": 1,
            "land_size": {"value": 149_800, "unit": "m2"},
            "address": {
                "street": "50 Millers Lane",
                "suburb": "Chatham Valley",
                "postcode": "2787",
                "state": "NSW",
                "latitude": -33.84,
                "longitude": 149.91,
            },
            "main_image": "https://example.com/property.jpg",
        }
        item = {
            "Listing ID": "700414500",
            "Listing URL": raw["url"],
            "Title": raw["title"],
            "Street": "50 Millers Lane",
            "Suburb": "Chatham Valley",
            "Postcode": "2787",
            "State": "NSW",
            "Price": "$750,000",
            "Property Type": "farmlet",
            "Beds": 2,
            "Baths": 1,
            "Latitude": -33.84,
            "Longitude": 149.91,
            "Photos": raw["main_image"],
            "Raw": json.dumps(raw),
        }

        prop = sources._normalize_apify_rea_listing(item, {"2787"})

        self.assertEqual(prop["source_id"], "rea-700414500")
        self.assertEqual(prop["price"], 750_000)
        self.assertAlmostEqual(prop["land_acres"], 37.0, places=1)
        self.assertEqual(prop["bedrooms"], 2)
        self.assertEqual(prop["headline"], "FROG HOLLOW - 37 ACRES")
        self.assertNotIn("<br", prop["description"])
        self.assertEqual(prop["listing_url"], raw["url"])

    def test_current_apify_schema_preserves_listing_quality_fields(self):
        item = {
            "propertyId": "700417256",
            "propertyType": "lifestyle",
            "address": {
                "full": "123 Test Road, Oberon, NSW 2787",
                "suburb": "Oberon",
                "state": "NSW",
                "postcode": "2787",
            },
            "coordinates": {"latitude": -33.7, "longitude": 149.9},
            "price": {"display": "$1,250,000"},
            "features": {"bedrooms": 4, "bathrooms": 2},
            "landSize": 149_700,
            "landSizeUnit": "m2",
            "headline": "A real rural listing",
            "description": "A useful description.",
            "url": "https://www.realestate.com.au/property-rural-nsw-oberon-123456789",
            "dateListed": "2026-08-07",
        }

        prop = sources._normalize_apify_rea_listing(item, {"2787"})

        self.assertEqual(prop["price"], 1_250_000)
        self.assertAlmostEqual(prop["land_acres"], 37.0, places=1)
        self.assertEqual(prop["headline"], "A real rural listing")
        self.assertEqual(prop["listing_url"], item["url"])
        self.assertEqual(prop["date_listed"], "2026-08-07")

    def test_farmbuy_transport_failure_is_not_reported_as_zero_results(self):
        session = Mock()
        session.get.side_effect = sources.requests.ConnectionError("offline")
        criteria = {
            "gates": {
                "geography": {"postcodes_west": ["2787"], "postcodes_south": []},
                "budget": {"min_price": 100_000, "max_price": 2_000_000},
            }
        }

        with patch.object(sources, "_retry_session", return_value=session):
            with self.assertRaisesRegex(sources.SourceFetchError, "Farmbuy request failed"):
                sources.fetch_farmbuy(criteria)

    def test_fetch_all_records_source_failures_for_guarded_publish(self):
        failure = sources.SourceFetchError("upstream unavailable")
        patches = (
            patch.object(sources, "fetch_domain", return_value=[]),
            patch.object(sources, "fetch_domain_web", return_value=[]),
            patch.object(sources, "fetch_farmbuy", side_effect=failure),
            patch.object(sources, "fetch_elders", return_value=[]),
            patch.object(sources, "fetch_rea_apify", return_value=[]),
            patch.object(sources, "fetch_rea_manual", return_value=[]),
            patch.object(sources, "fetch_email_alerts", return_value=[]),
        )

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            properties, report = sources.fetch_all({})

        self.assertEqual(properties, [])
        self.assertEqual(report["Farmbuy"]["count"], 0)
        self.assertEqual(report["Farmbuy"]["error"], "upstream unavailable")

    def test_inventory_is_pre_dedup_and_excludes_rolling_alert_sources(self):
        domain = {
            "source": "domain_web", "source_id": "domain-1",
            "address": "1 Test Road", "suburb": "Testville", "postcode": "2787",
        }
        farmbuy = {
            "source": "farmbuy", "source_id": "farmbuy-1",
            "address": "1 Test Road", "suburb": "Testville", "postcode": "2787",
        }
        email = {
            "source": "cre", "source_id": "cre-1",
            "address": "2 Test Road", "suburb": "Testville", "postcode": "2787",
        }

        with (
            patch.object(sources, "fetch_domain", return_value=[]),
            patch.object(sources, "fetch_domain_web", return_value=[domain]),
            patch.object(sources, "fetch_farmbuy", return_value=[farmbuy]),
            patch.object(sources, "fetch_elders", return_value=[]),
            patch.object(sources, "fetch_rea_apify", return_value=[]),
            patch.object(sources, "fetch_rea_manual", return_value=[]),
            patch.object(sources, "fetch_email_alerts", return_value=[email]),
        ):
            properties, _, inventory = sources.fetch_all({}, include_inventory=True)

        self.assertEqual(len(properties), 2)
        self.assertEqual(
            {(item["source"], item["source_id"]) for item in inventory},
            {("domain_web", "domain-1"), ("farmbuy", "farmbuy-1")},
        )

    def test_missing_email_credentials_are_a_source_failure(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(sources.SourceFetchError, "credentials are missing"):
                sources.fetch_email_alerts({})

    def test_explicit_imap_failures_are_not_reported_as_zero_alerts(self):
        mail = Mock()
        mail.select.return_value = ("OK", [b""])
        mail.search.return_value = ("NO", [b""])

        with self.assertRaisesRegex(sources.SourceFetchError, "search failed"):
            sources._search_emails_from(mail, ["alerts@example.com"])

        mail.select.return_value = ("NO", [b""])
        with self.assertRaisesRegex(sources.SourceFetchError, "could not select INBOX"):
            sources._search_emails_from(mail, ["alerts@example.com"])

        mail.select.return_value = ("OK", [b""])
        mail.search.return_value = ("OK", [b"1"])
        mail.fetch.return_value = ("BAD", [])
        with self.assertRaisesRegex(sources.SourceFetchError, "message fetch failed"):
            sources._search_emails_from(mail, ["alerts@example.com"])

        mail.fetch.return_value = ("OK", [])
        with self.assertRaisesRegex(sources.SourceFetchError, "malformed message response"):
            sources._search_emails_from(mail, ["alerts@example.com"])


if __name__ == "__main__":
    unittest.main()
