import unittest

from watchdog import detect_auth_errors


class DetectAuthErrorsTests(unittest.TestCase):
    def test_first_occurrence_alerts_once(self) -> None:
        data = [
            {
                "provider": "claude",
                "error": {"message": "Claude OAuth credentials not found.", "code": 3},
            }
        ]

        newly_erroring, state_updates = detect_auth_errors(data, {"claude"}, {})

        self.assertEqual(newly_erroring, [("claude", "Claude OAuth credentials not found.")])
        self.assertEqual(state_updates, {"claude": {"authErrorActive": True}})

    def test_repeated_error_does_not_alert_again(self) -> None:
        data = [
            {
                "provider": "claude",
                "error": {"message": "Claude OAuth credentials not found.", "code": 3},
            }
        ]
        old_state = {"claude": {"authErrorActive": True}}

        newly_erroring, state_updates = detect_auth_errors(data, {"claude"}, old_state)

        self.assertEqual(newly_erroring, [])
        self.assertEqual(state_updates, {"claude": {"authErrorActive": True}})

    def test_recovery_clears_flag_without_alerting(self) -> None:
        data = [{"provider": "claude", "usage": {}}]
        old_state = {"claude": {"authErrorActive": True}}

        newly_erroring, state_updates = detect_auth_errors(data, {"claude"}, old_state)

        self.assertEqual(newly_erroring, [])
        self.assertEqual(state_updates, {"claude": {"authErrorActive": False}})

    def test_new_error_after_recovery_alerts_again(self) -> None:
        data = [
            {
                "provider": "claude",
                "error": {"message": "Claude OAuth credentials not found.", "code": 3},
            }
        ]
        old_state = {"claude": {"authErrorActive": False}}

        newly_erroring, state_updates = detect_auth_errors(data, {"claude"}, old_state)

        self.assertEqual(newly_erroring, [("claude", "Claude OAuth credentials not found.")])
        self.assertEqual(state_updates, {"claude": {"authErrorActive": True}})

    def test_provider_without_error_and_no_prior_state_is_untouched(self) -> None:
        data = [{"provider": "claude", "usage": {}}]

        newly_erroring, state_updates = detect_auth_errors(data, {"claude"}, {})

        self.assertEqual(newly_erroring, [])
        self.assertEqual(state_updates, {})


if __name__ == "__main__":
    unittest.main()
