import subprocess
import unittest
from unittest.mock import patch

from watchdog import get_usage_data


class GetUsageDataTests(unittest.TestCase):
    @patch("watchdog.subprocess.run")
    def test_accepts_partial_json_even_when_codexbar_exits_non_zero(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["codexbar", "usage", "--format", "json"],
            returncode=1,
            stdout='[{"provider":"codex","usage":{"secondary":{"usedPercent":7}}}]',
            stderr="",
        )

        data = get_usage_data()

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["provider"], "codex")

    @patch("watchdog.subprocess.run")
    def test_raises_when_codexbar_returns_no_json_output(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["codexbar", "usage", "--format", "json"],
            returncode=1,
            stdout="",
            stderr="provider unavailable",
        )

        with self.assertRaisesRegex(RuntimeError, "codexbar exited 1: provider unavailable"):
            get_usage_data()

    @patch("watchdog.subprocess.run")
    def test_claude_errored_via_oauth_is_replaced_by_working_web_source(self, mock_run) -> None:
        """The primary call's 'claude' entry (default/oauth source) errors —
        e.g. CodexBar's internal OAuth Keychain cache is stale — but the
        follow-up --source web re-fetch succeeds, so the final data should
        carry the web-sourced (working) entry, not the errored one."""

        def side_effect(cmd, **kwargs):
            if "--source" in cmd and cmd[cmd.index("--source") + 1] == "web":
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout='[{"provider":"claude","source":"web","usage":{"secondary":{"usedPercent":40}}}]',
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=3,
                stdout=(
                    '[{"provider":"codex","usage":{"secondary":{"usedPercent":7}}},'
                    '{"provider":"claude","source":"oauth",'
                    '"error":{"message":"Claude OAuth credentials not found.","code":3}}]'
                ),
                stderr="",
            )

        mock_run.side_effect = side_effect

        data = get_usage_data()

        claude = next(p for p in data if p["provider"] == "claude")
        self.assertNotIn("error", claude)
        self.assertEqual(claude["source"], "web")
        self.assertEqual(claude["usage"]["secondary"]["usedPercent"], 40)

    @patch("watchdog.subprocess.run")
    def test_claude_error_kept_when_web_source_also_fails(self, mock_run) -> None:
        """If --source web also errors (or fails outright), the original
        (oauth-sourced) error must still surface — never silently hidden."""

        def side_effect(cmd, **kwargs):
            if "--source" in cmd and cmd[cmd.index("--source") + 1] == "web":
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=3,
                    stdout='[{"provider":"claude","source":"web","error":{"message":"Not logged in.","code":3}}]',
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=3,
                stdout=(
                    '[{"provider":"claude","source":"oauth",'
                    '"error":{"message":"Claude OAuth credentials not found.","code":3}}]'
                ),
                stderr="",
            )

        mock_run.side_effect = side_effect

        data = get_usage_data()

        claude = next(p for p in data if p["provider"] == "claude")
        self.assertEqual(claude["source"], "oauth")
        self.assertEqual(claude["error"]["message"], "Claude OAuth credentials not found.")


if __name__ == "__main__":
    unittest.main()
