import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import scheduled_refresh


class ScheduledRefreshTests(unittest.TestCase):
    def test_dirty_site_fails_before_refresh_or_publish(self):
        with (
            patch.object(scheduled_refresh, "_site_is_dirty", return_value=True),
            patch.object(scheduled_refresh, "_run") as run,
            patch.object(scheduled_refresh, "_write_status") as write_status,
            patch.object(scheduled_refresh, "_notify_failure") as notify,
        ):
            self.assertEqual(scheduled_refresh.main(), 1)

        run.assert_not_called()
        write_status.assert_called_once()
        self.assertFalse(write_status.call_args.args[0])
        notify.assert_called_once()

    def test_publish_stages_the_complete_public_bundle_and_pushes_main(self):
        branch = Mock(stdout="main\n")
        with (
            patch.object(scheduled_refresh, "_run", side_effect=[branch, Mock(), Mock(), Mock()]) as run,
            patch.object(subprocess, "run", return_value=Mock(returncode=1)),
        ):
            self.assertEqual(scheduled_refresh._publish_site(), "pushed")

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[1][0:3], ["git", "add", "--"])
        self.assertIn("docs/index.html", commands[1])
        self.assertIn("docs/site-state.json", commands[1])
        self.assertIn("docs/bolt-hole-overview.html", commands[1])
        self.assertEqual(commands[2][0:3], ["git", "commit", "--only"])
        self.assertIn("docs/site-state.json", commands[2])
        self.assertEqual(commands[3], ["git", "push", "origin", "HEAD:main"])

    def test_unchanged_site_still_pushes_a_previously_committed_refresh(self):
        branch = Mock(stdout="main\n")
        with (
            patch.object(scheduled_refresh, "_run", side_effect=[branch, Mock()]) as run,
            patch.object(subprocess, "run", return_value=Mock(returncode=0)),
        ):
            self.assertEqual(scheduled_refresh._publish_site(), "unchanged")

        self.assertEqual(
            run.call_args_list[1].args[0],
            ["git", "push", "origin", "HEAD:main"],
        )

    def test_guarded_status_must_be_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.json"
            status_path.write_text(json.dumps({"ok": False, "problems": ["Domain too low"]}))
            with patch.object(scheduled_refresh, "GUARDED_STATUS", status_path):
                with self.assertRaisesRegex(
                    scheduled_refresh.ScheduledRefreshError, "Domain too low"
                ):
                    scheduled_refresh._verify_guarded_result()


if __name__ == "__main__":
    unittest.main()
