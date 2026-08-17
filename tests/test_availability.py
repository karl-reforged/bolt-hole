import unittest

from availability import availability_status, is_archived_status, status_label
from shortlist import _partition_props


class AvailabilityTests(unittest.TestCase):
    def test_missing_listing_moves_from_warning_to_archive(self):
        prop = {"source_id": "one"}
        self.assertEqual(availability_status(prop), "active")
        self.assertEqual(
            availability_status(prop, missing_from_latest=True, missing_days=3),
            "possibly_unavailable",
        )
        self.assertEqual(
            availability_status(prop, missing_from_latest=True, missing_days=22),
            "archived",
        )
        self.assertEqual(
            availability_status(
                {"status": "possibly_unavailable"},
                missing_from_latest=True,
                missing_days=22,
            ),
            "archived",
        )

    def test_clear_listing_labels_are_archived_without_false_sold_matches(self):
        self.assertEqual(
            availability_status({"display_price": "*** UNDER OFFER ***"}),
            "under_offer",
        )
        self.assertEqual(
            availability_status({"display_price": "Under Contract"}),
            "under_offer",
        )
        self.assertEqual(availability_status({"display_price": "SOLD"}), "sold")
        self.assertEqual(
            availability_status({"display_price": "SOLD", "headline": "Beautiful farm"}),
            "sold",
        )
        self.assertEqual(availability_status({"badge": "Withdrawn"}), "withdrawn")
        self.assertEqual(
            availability_status({"display_price": "Auction (Unless Sold Prior)"}),
            "active",
        )

    def test_explicit_terminal_status_wins_and_has_plain_label(self):
        for status in ("under_offer", "sold", "withdrawn", "archived"):
            with self.subTest(status=status):
                self.assertEqual(availability_status({"status": status}), status)
                self.assertTrue(is_archived_status(status))
                self.assertTrue(status_label(status))

    def test_top_n_view_does_not_append_the_archive(self):
        properties = [
            {"source_id": "active-1"},
            {"source_id": "active-2"},
            {"source_id": "sold", "status": "sold"},
        ]
        active, archived, total_found = _partition_props(properties, max_properties=1)

        self.assertEqual([p["source_id"] for p in active], ["active-1"])
        self.assertEqual(archived, [])
        self.assertEqual(total_found, 2)


if __name__ == "__main__":
    unittest.main()
