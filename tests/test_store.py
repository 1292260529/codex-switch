import base64
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from codex_switch.store import AccountPool, CodexSwitchError
from codex_switch.usage import UsageSnapshot


NOW = datetime.fromisoformat("2026-05-23T12:00:00+08:00")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.codex_home = Path(self.tmp.name) / ".codex"
        self.codex_home.mkdir()
        self.write_auth("initial")
        self.pool = AccountPool(self.codex_home, now=NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def write_auth(self, value):
        email = value if "@" in value else f"{value}@example.com"
        (self.codex_home / "auth.json").write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "account_id": value,
                        "id_token": self.jwt_for_email(email),
                    },
                }
            ),
            encoding="utf-8",
        )

    def jwt_for_email(self, email):
        payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode()
        return f"header.{payload.rstrip('=')}.signature"

    def read_auth_id(self):
        return json.loads((self.codex_home / "auth.json").read_text(encoding="utf-8"))["tokens"][
            "account_id"
        ]

    def add_account(self, alias, account_id, next_refresh):
        self.write_auth(account_id)
        return self.pool.add_account(alias, next_refresh)

    def test_add_requires_valid_date(self):
        with self.assertRaises(CodexSwitchError):
            self.pool.add_account("a", "bad-date")

    def test_add_writes_secure_files(self):
        self.pool.add_account("a", "2026-05-30")
        pool_mode = stat.S_IMODE(os.stat(self.codex_home / "account-pool").st_mode)
        auth_mode = stat.S_IMODE(
            os.stat(self.codex_home / "account-pool" / "accounts" / "a" / "auth.json").st_mode
        )
        self.assertEqual(pool_mode, 0o700)
        self.assertEqual(auth_mode, 0o600)

    def test_add_defaults_alias_to_login_email(self):
        self.write_auth("user@example.com")
        self.pool.add_account(None, "2026-05-30")
        data = json.loads((self.codex_home / "account-pool" / "accounts.json").read_text())
        self.assertEqual(data["accounts"][0]["alias"], "user@example.com")

    def test_add_defaults_next_refresh_to_usage_reset(self):
        self.write_auth("user@example.com")
        pool = AccountPool(
            self.codex_home,
            now=NOW,
            usage_fetcher=lambda auth: UsageSnapshot(
                "available",
                15,
                85,
                "1周",
                datetime.fromisoformat("2026-05-30T00:00:00+08:00"),
            ),
        )
        pool.add_account(None)
        data = json.loads((self.codex_home / "account-pool" / "accounts.json").read_text())
        self.assertEqual(data["accounts"][0]["next_refresh_at"], "2026-05-30")
        self.assertEqual(data["accounts"][0]["usage_remaining_percent"], 85)

    def test_current_next_refresh_uses_usage_reset(self):
        pool = AccountPool(
            self.codex_home,
            now=NOW,
            usage_fetcher=lambda auth: UsageSnapshot(
                "available",
                15,
                85,
                "1周",
                datetime.fromisoformat("2026-05-30T00:00:00+08:00"),
            ),
        )
        self.assertEqual(pool.current_next_refresh(), "2026-05-30")

    def test_add_without_next_refresh_requires_usage_reset(self):
        pool = AccountPool(
            self.codex_home,
            now=NOW,
            usage_fetcher=lambda auth: UsageSnapshot("available", None, None, None, None),
        )
        with self.assertRaisesRegex(CodexSwitchError, "--next-refresh"):
            pool.add_account("a")

    def test_add_overwrites_existing_email_account(self):
        self.write_auth("user@example.com")
        self.pool.add_account(None, "2026-05-30", note="old")
        self.write_auth("user@example.com")
        result = self.pool.add_account(None, "2026-06-06", note="new")
        data = json.loads((self.codex_home / "account-pool" / "accounts.json").read_text())
        self.assertEqual(result, "updated user@example.com")
        self.assertEqual(len(data["accounts"]), 1)
        self.assertEqual(data["accounts"][0]["next_refresh_at"], "2026-06-06")
        self.assertEqual(data["accounts"][0]["note"], "new")

    def test_sync_emails_renames_existing_aliases(self):
        self.add_account("a", "user-a@example.com", "2026-05-30")
        result = self.pool.sync_emails()
        self.assertIn("a -> user-a@example.com", result)
        data = json.loads((self.codex_home / "account-pool" / "accounts.json").read_text())
        self.assertEqual(data["accounts"][0]["alias"], "user-a@example.com")
        self.assertTrue(
            (self.codex_home / "account-pool" / "accounts" / "user-a@example.com" / "auth.json").exists()
        )

    def test_use_switches_and_updates_current(self):
        self.add_account("a", "account-a", "2026-05-30")
        self.add_account("b", "account-b", "2026-05-29")
        self.pool.use_account("a")
        self.assertEqual(self.read_auth_id(), "account-a")
        data = json.loads((self.codex_home / "account-pool" / "accounts.json").read_text())
        self.assertEqual(data["current"], "a")

    def test_prepare_add_removes_local_auth_without_dropping_saved_account(self):
        self.add_account("a", "account-a", "2026-05-30")
        self.pool.use_account("a")
        result = self.pool.prepare_add()
        self.assertIn("prepared login for a new account", result)
        self.assertFalse((self.codex_home / "auth.json").exists())
        self.assertTrue(
            (self.codex_home / "account-pool" / "accounts" / "a" / "auth.json").exists()
        )
        backups = list((self.codex_home / "account-pool" / "backups").glob("auth-*.json"))
        self.assertEqual(len(backups), 2)

    def test_use_works_after_prepare_add_removed_auth(self):
        self.add_account("a", "account-a", "2026-05-30")
        self.pool.prepare_add()
        self.pool.use_account("a")
        self.assertEqual(self.read_auth_id(), "account-a")

    def test_current_falls_back_to_email_match(self):
        self.add_account("user@example.com", "user@example.com", "2026-05-30")
        self.write_auth("user@example.com")
        self.assertIn("current=user@example.com", self.pool.current())

    def test_auto_uses_earliest_available_refresh(self):
        self.add_account("a", "account-a", "2026-05-30")
        self.add_account("b", "account-b", "2026-05-29")
        ok, message = self.pool.auto_switch()
        self.assertTrue(ok)
        self.assertIn("a", message)
        self.assertEqual(self.read_auth_id(), "account-a")

    def test_auto_skips_current_account(self):
        self.add_account("a", "account-a", "2026-05-29")
        self.add_account("b", "account-b", "2026-05-30")
        self.pool.use_account("a")
        ok, message = self.pool.auto_switch()
        self.assertTrue(ok)
        self.assertIn("b", message)
        self.assertEqual(self.read_auth_id(), "account-b")

    def test_auto_reports_when_only_current_is_available(self):
        self.add_account("a", "account-a", "2026-05-29")
        self.add_account("b", "account-b", "2026-05-30")
        self.pool.use_account("a")
        self.pool.mark("b", "unavailable")
        ok, message = self.pool.auto_switch()
        self.assertFalse(ok)
        self.assertIn("no available non-current accounts", message)
        self.assertEqual(self.read_auth_id(), "account-a")

    def test_auto_refreshes_due_unavailable_account(self):
        self.add_account("a", "account-a", "2026-05-23")
        self.add_account("b", "account-b", "2026-05-30")
        self.pool.use_account("b")
        self.pool.mark("a", "unavailable")
        ok, message = self.pool.auto_switch()
        self.assertTrue(ok)
        self.assertIn("a", message)
        data = json.loads((self.codex_home / "account-pool" / "accounts.json").read_text())
        self.assertEqual(data["accounts"][0]["status"], "available")
        self.assertEqual(data["accounts"][0]["next_refresh_at"], "2026-05-30")

    def test_auto_refreshes_due_available_account(self):
        self.add_account("a", "account-a", "2026-05-23")
        self.add_account("b", "account-b", "2026-05-30")
        self.pool.use_account("b")
        ok, message = self.pool.auto_switch()
        self.assertTrue(ok)
        self.assertIn("a", message)
        data = json.loads((self.codex_home / "account-pool" / "accounts.json").read_text())
        self.assertEqual(data["accounts"][0]["last_checked_at"], "2026-05-23T12:00:00+08:00")
        self.assertEqual(data["accounts"][0]["next_refresh_at"], "2026-05-30")

    def test_mark_unavailable_does_not_change_next_refresh(self):
        self.add_account("a", "account-a", "2026-05-30")
        self.pool.mark("a", "unavailable")
        data = json.loads((self.codex_home / "account-pool" / "accounts.json").read_text())
        self.assertEqual(data["accounts"][0]["status"], "unavailable")
        self.assertEqual(data["accounts"][0]["next_refresh_at"], "2026-05-30")

    def test_auto_reports_when_none_available(self):
        self.add_account("a", "account-a", "2026-05-30")
        self.pool.mark("a", "unavailable")
        self.write_auth("original")
        ok, message = self.pool.auto_switch()
        self.assertFalse(ok)
        self.assertIn("no available non-current accounts", message)
        self.assertIn("next_refresh=2026-05-30", message)
        self.assertEqual(self.read_auth_id(), "original")

    def test_list_refreshes_usage_metadata(self):
        self.add_account("a", "account-a", "2026-05-29")
        pool = AccountPool(
            self.codex_home,
            now=NOW,
            usage_fetcher=lambda auth: UsageSnapshot(
                "available",
                15,
                85,
                "1周",
                datetime.fromisoformat("2026-05-30T00:00:00+08:00"),
            ),
        )
        output = pool.list_accounts()
        self.assertIn("usage=used=15% remaining=85% 1周 reset=2026-05-30", output)
        data = json.loads((self.codex_home / "account-pool" / "accounts.json").read_text())
        self.assertEqual(data["accounts"][0]["status"], "available")
        self.assertEqual(data["accounts"][0]["next_refresh_at"], "2026-05-30")
        self.assertEqual(data["accounts"][0]["usage_remaining_percent"], 85)

    def test_total_available_percent_sums_account_remaining_usage(self):
        self.add_account("a", "account-a", "2026-05-29")
        self.add_account("b", "account-b", "2026-05-29")

        def fake_usage(auth):
            account_id = auth["tokens"]["account_id"]
            remaining = 85 if account_id == "account-a" else 25
            return UsageSnapshot(
                "available",
                100 - remaining,
                remaining,
                "1周",
                datetime.fromisoformat("2026-05-30T00:00:00+08:00"),
            )

        pool = AccountPool(self.codex_home, now=NOW, usage_fetcher=fake_usage)
        self.assertEqual(pool.total_available_percent(), 110)

    def test_auto_uses_usage_status_before_switching(self):
        self.add_account("a", "account-a", "2026-05-29")
        self.add_account("b", "account-b", "2026-05-29")

        def fake_usage(auth):
            account_id = auth["tokens"]["account_id"]
            if account_id == "account-a":
                return UsageSnapshot(
                    "unavailable",
                    100,
                    0,
                    "1周",
                    datetime.fromisoformat("2026-05-30T00:00:00+08:00"),
                )
            return UsageSnapshot(
                "available",
                75,
                25,
                "1周",
                datetime.fromisoformat("2026-05-31T00:00:00+08:00"),
            )

        pool = AccountPool(self.codex_home, now=NOW, usage_fetcher=fake_usage)
        pool.use_account("a")
        ok, message = pool.auto_switch()
        self.assertTrue(ok)
        self.assertIn("b", message)
        self.assertEqual(self.read_auth_id(), "account-b")

    def test_invalid_current_auth_blocks_add(self):
        (self.codex_home / "auth.json").write_text("{bad", encoding="utf-8")
        with self.assertRaises(CodexSwitchError):
            self.pool.add_account("a", "2026-05-30")


if __name__ == "__main__":
    unittest.main()
