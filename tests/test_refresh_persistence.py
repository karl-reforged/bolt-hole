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
        self.assertFalse(json.loads(post.call_args.kwargs["data"])["full_snapshot"])

    def test_database_upsert_fails_closed_without_admin_token(self):
        with (
            patch.object(search, "NOTES_URL", "https://worker.example"),
            patch.object(search, "BOLT_ADMIN_TOKEN", ""),
            patch.object(search.requests, "post") as post,
            patch.dict(search.os.environ, {"BOLT_SKIP_SHEET_UPSERT": "0"}),
        ):
            self.assertFalse(search._upsert_properties_to_sheet([{"source_id": "one"}]))
        post.assert_not_called()

    def test_refresh_command_enables_database_upsert(self):
        refresh = Path("refresh.sh").read_text()
        self.assertIn("--upsert", refresh)
        guarded = Path("run_guarded_domain_refresh.py").read_text()
        self.assertIn("full_snapshot=True", guarded)


if __name__ == "__main__":
    unittest.main()
