import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import search


class RefreshPersistenceTests(unittest.TestCase):
    def test_database_upsert_is_authenticated_and_confirmed(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True, "upserted": 1}
        properties = [{"source_id": "one", "listing_url": "https://example.com/one"}]

        with (
            patch.object(search, "NOTES_URL", "https://worker.example"),
            patch.object(search, "BOLT_ADMIN_TOKEN", "private-admin-token"),
            patch.object(search.requests, "post", return_value=response) as post,
            patch.dict(search.os.environ, {"BOLT_SKIP_SHEET_UPSERT": "0"}),
        ):
            self.assertTrue(search._upsert_properties_to_sheet(properties))

        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer private-admin-token")
        self.assertEqual(post.call_args.kwargs["headers"]["Content-Type"], "application/json")
        body = json.loads(post.call_args.kwargs["data"])
        self.assertFalse(body["full_snapshot"])
        self.assertEqual(body["source_inventory"], [])

    def test_database_upsert_fails_closed_without_admin_token(self):
        with (
            patch.object(search, "NOTES_URL", "https://worker.example"),
            patch.object(search, "BOLT_ADMIN_TOKEN", ""),
            patch.object(search.requests, "post") as post,
            patch.dict(search.os.environ, {"BOLT_SKIP_SHEET_UPSERT": "0"}),
        ):
            self.assertFalse(search._upsert_properties_to_sheet([{"source_id": "one"}]))
        post.assert_not_called()

    def test_full_snapshot_requires_and_sends_complete_source_inventory(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True, "upserted": 1}
        properties = [{"source_id": "passing", "source": "domain_web"}]
        inventory = [
            {"source_id": "passing", "source": "domain_web"},
            {"source_id": "filtered", "source": "domain_web"},
        ]

        with (
            patch.object(search, "NOTES_URL", "https://worker.example"),
            patch.object(search, "BOLT_ADMIN_TOKEN", "private-admin-token"),
            patch.object(search.requests, "post", return_value=response) as post,
            patch.dict(search.os.environ, {"BOLT_SKIP_SHEET_UPSERT": "0"}),
        ):
            self.assertFalse(search._upsert_properties_to_sheet(properties, full_snapshot=True))
            self.assertTrue(search._upsert_properties_to_sheet(
                properties,
                full_snapshot=True,
                source_inventory=inventory,
            ))

        self.assertEqual(post.call_count, 1)
        body = json.loads(post.call_args.kwargs["data"])
        self.assertTrue(body["full_snapshot"])
        self.assertEqual(body["source_inventory"], inventory)

    def test_refresh_command_enables_database_upsert(self):
        refresh = Path("refresh.sh").read_text()
        self.assertIn("--upsert", refresh)
        guarded = Path("run_guarded_domain_refresh.py").read_text()
        self.assertIn("full_snapshot=True", guarded)
        self.assertIn("source_inventory=data.get('source_inventory', [])", guarded)


if __name__ == "__main__":
    unittest.main()
