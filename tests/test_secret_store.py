import unittest
from unittest.mock import Mock, patch

import secret_store


class SecretStoreTests(unittest.TestCase):
    def test_keychain_lookup_uses_the_operating_system_account(self):
        result = Mock(stdout="admin-token\n")
        with (
            patch.dict(secret_store.os.environ, {}, clear=True),
            patch.object(secret_store.sys, "platform", "darwin"),
            patch.object(secret_store.getpass, "getuser", return_value="karlhoward"),
            patch.object(secret_store.subprocess, "run", return_value=result) as run,
        ):
            self.assertEqual(secret_store.get_admin_token(), "admin-token")

        self.assertEqual(
            run.call_args.args[0][0:4],
            ["security", "find-generic-password", "-a", "karlhoward"],
        )


if __name__ == "__main__":
    unittest.main()
