import os
import importlib.util
import unittest
from unittest.mock import Mock, patch

import sources


class SourceResilienceTests(unittest.TestCase):
    def test_elders_pdf_dependency_is_installed(self):
        self.assertIsNotNone(importlib.util.find_spec("pdfplumber"))

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
                    "postcodes_south": [],
                },
                "budget": {"min_price": 100_000, "max_price": 2_000_000},
            }
        }

        with (
            patch.dict(
                os.environ,
                {
                    "APIFY_API_TOKEN": "private-apify-token",
                    "APIFY_REA_ACTOR": "owner/actor",
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
