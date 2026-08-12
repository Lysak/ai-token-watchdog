import unittest
from datetime import datetime, timedelta, timezone

from watchdog import should_notify_error


class ShouldNotifyErrorTests(unittest.TestCase):
    def test_notifies_when_no_prior_error_recorded(self) -> None:
        self.assertTrue(should_notify_error({}))

    def test_suppresses_within_cooldown_window(self) -> None:
        recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        state = {"_error": {"lastNotifiedAt": recent}}

        self.assertFalse(should_notify_error(state))

    def test_notifies_again_after_cooldown_expires(self) -> None:
        stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        state = {"_error": {"lastNotifiedAt": stale}}

        self.assertTrue(should_notify_error(state))


if __name__ == "__main__":
    unittest.main()
