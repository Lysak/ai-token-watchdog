import unittest

from watchdog import detect_resets


class DetectResetsTests(unittest.TestCase):
    def test_codex_does_not_reset_on_resets_at_drift_when_usage_stays_zero(self) -> None:
        data = [
            {
                "provider": "codex",
                "usage": {
                    "secondary": {
                        "usedPercent": 0,
                        "resetsAt": "2026-07-25T11:02:35Z",
                        "resetDescription": "Jul 25 at 2:02 PM",
                    }
                },
            }
        ]
        old_state = {
            "codex": {
                "usedPercent": 0,
                "maxUsedPercent": 0,
                "resetsAt": "2026-07-25T11:00:59Z",
                "lastNotifiedAt": None,
            }
        }

        resets, new_state = detect_resets(data, {"codex"}, old_state)

        self.assertEqual(resets, [])
        self.assertEqual(new_state["codex"]["usedPercent"], 0)
        self.assertEqual(new_state["codex"]["maxUsedPercent"], 0)

    def test_codex_resets_when_cycle_advances_after_non_zero_usage(self) -> None:
        data = [
            {
                "provider": "codex",
                "usage": {
                    "secondary": {
                        "usedPercent": 0,
                        "resetsAt": "2026-07-25T11:02:35Z",
                        "resetDescription": "Jul 25 at 2:02 PM",
                    }
                },
            }
        ]
        old_state = {
            "codex": {
                "usedPercent": 37,
                "maxUsedPercent": 37,
                "resetsAt": "2026-07-18T08:55:00Z",
                "lastNotifiedAt": None,
            }
        }

        resets, new_state = detect_resets(data, {"codex"}, old_state)

        self.assertEqual(len(resets), 1)
        self.assertEqual(resets[0][0], "codex")
        self.assertEqual(resets[0][2]["usedPercent"], 37)
        self.assertEqual(new_state["codex"]["maxUsedPercent"], 0)

    def test_codex_does_not_reset_when_usage_does_not_drop(self) -> None:
        data = [
            {
                "provider": "codex",
                "usage": {
                    "secondary": {
                        "usedPercent": 8,
                        "resetsAt": "2026-07-25T11:02:35Z",
                        "resetDescription": "Jul 25 at 2:02 PM",
                    }
                },
            }
        ]
        old_state = {
            "codex": {
                "usedPercent": 8,
                "maxUsedPercent": 8,
                "resetsAt": "2026-07-25T11:00:59Z",
                "lastNotifiedAt": None,
            }
        }

        resets, new_state = detect_resets(data, {"codex"}, old_state)

        self.assertEqual(resets, [])
        self.assertEqual(new_state["codex"]["maxUsedPercent"], 8)

    def test_codex_resets_when_usage_drops_without_zeroing(self) -> None:
        data = [
            {
                "provider": "codex",
                "usage": {
                    "secondary": {
                        "usedPercent": 6,
                        "resetsAt": "2026-07-25T11:02:35Z",
                        "resetDescription": "Jul 25 at 2:02 PM",
                    }
                },
            }
        ]
        old_state = {
            "codex": {
                "usedPercent": 8,
                "maxUsedPercent": 8,
                "resetsAt": "2026-07-25T11:00:59Z",
                "lastNotifiedAt": None,
            }
        }

        resets, new_state = detect_resets(data, {"codex"}, old_state)

        self.assertEqual(len(resets), 1)
        self.assertEqual(resets[0][2]["usedPercent"], 8)
        self.assertEqual(new_state["codex"]["maxUsedPercent"], 6)


if __name__ == "__main__":
    unittest.main()
