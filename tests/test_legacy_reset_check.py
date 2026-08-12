import sys
import unittest
from unittest.mock import patch

import watchdog


class LegacyResetCheckTests(unittest.TestCase):
    def test_reset_check_flag_runs_the_normal_monitor(self) -> None:
        sent = []

        with (
            patch.object(watchdog, "TELEGRAM_TOKEN", "token"),
            patch.object(watchdog, "TELEGRAM_CHAT_ID", "chat"),
            patch.object(watchdog, "get_usage_data", return_value=[]),
            patch.object(watchdog, "clear_error_cooldown"),
            patch.object(watchdog, "get_enabled_providers", return_value=set()),
            patch.object(watchdog, "build_monitor_message", return_value="monitor report"),
            patch.object(watchdog, "check_resets", side_effect=AssertionError("legacy reset check ran")),
            patch.object(watchdog, "send_telegram", side_effect=lambda text, mode: sent.append((text, mode))),
            patch.object(sys, "argv", ["watchdog.py", "--reset-check"]),
        ):
            watchdog.main()

        self.assertEqual(sent, [("monitor report", "monitor")])


if __name__ == "__main__":
    unittest.main()
