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


if __name__ == "__main__":
    unittest.main()
