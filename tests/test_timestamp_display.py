import unittest
from datetime import datetime

import watchdog


class TimestampDisplayTests(unittest.TestCase):
    def test_reset_and_expiry_timestamps_include_date_time_seconds_and_today(self) -> None:
        # Catches a return to CodexBar's malformed resetDescription display text.
        reset_line = watchdog._limit_line(
            "5h ",
            {
                "usedPercent": 17,
                "resetsAt": "2026-08-14T16:30:45Z",
                "resetDescription": "Resets7:30pm(Europe/Kiev)",
            },
        )
        expiry_line = watchdog._codex_reset_credits_line(
            {"codexResetCredits": {"credits": [{"status": "available", "expires_at": "2026-08-14T16:30:45Z"}]}}
        )
        today = datetime.now(watchdog.TZ).replace(microsecond=0)

        self.assertIn("Aug 14, 2026 at 19:30:45 (Europe/Kyiv)", reset_line)
        self.assertIn("expires Aug 14, 2026 at 19:30:45 (Europe/Kyiv)", expiry_line)
        self.assertTrue(watchdog._format_timestamp(today.isoformat()).endswith("(today!)"))

    def test_invalid_reset_timestamp_uses_question_mark(self) -> None:
        self.assertTrue(watchdog._limit_line("5h ", {"usedPercent": 17, "resetsAt": "invalid"}).endswith("↻ ?"))


if __name__ == "__main__":
    unittest.main()
