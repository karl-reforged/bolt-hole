import unittest

from feedback_report import build_feedback_summary


class FeedbackReportTests(unittest.TestCase):
    def test_feedback_is_grouped_by_person_and_property_tags(self):
        export = {
            "properties": [
                {"source_id": "creek", "payload": {"tags": ["water", "secluded"]}},
                {"source_id": "road", "payload": {"tags": ["road_noise"]}},
            ],
            "notes": [{
                "id": "note-1", "property_id": "creek", "author": "George",
                "timestamp": "2026-08-17T01:00:00Z", "note": "The creek is the key feature.",
            }],
            "reactions": [
                {"property_id": "creek", "author": "George", "reaction": "love"},
                {"property_id": "road", "author": "Mary", "reaction": "pass"},
            ],
            "favourites": [
                {"property_id": "creek", "author": "Mary"},
            ],
        }

        summary = build_feedback_summary(export, generated_at="2026-08-17T02:00:00Z")

        self.assertEqual(summary["participants"]["George"]["notes"], 1)
        self.assertEqual(summary["participants"]["George"]["reactions"]["love"], 1)
        self.assertEqual(summary["participants"]["Mary"]["favourites"], 1)
        self.assertEqual(summary["signals"]["overall"]["water"], {"events": 2, "score": 4})
        self.assertEqual(summary["signals"]["overall"]["road_noise"], {"events": 1, "score": -2})
        self.assertEqual(summary["notes"][0]["author"], "George")
        self.assertEqual(summary["notes"][0]["note"], "The creek is the key feature.")

    def test_unknown_properties_do_not_create_misleading_tag_signals(self):
        summary = build_feedback_summary({
            "properties": [],
            "notes": [],
            "reactions": [{"property_id": "missing", "author": "George", "reaction": "love"}],
            "favourites": [],
        }, generated_at="2026-08-17T02:00:00Z")
        self.assertEqual(summary["signals"]["overall"], {})
        self.assertEqual(summary["unmatched_feedback_events"], 1)


if __name__ == "__main__":
    unittest.main()
