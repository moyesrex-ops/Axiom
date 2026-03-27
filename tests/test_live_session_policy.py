import unittest

from core.live_session_policy import (
    compute_rotation_deadline,
    parse_duration_seconds,
    should_rotate_now,
)


class LiveSessionPolicyTests(unittest.TestCase):
    def test_parse_duration_seconds_supports_compound_text(self):
        self.assertEqual(parse_duration_seconds("1m 30s"), 90.0)
        self.assertEqual(parse_duration_seconds("750ms"), 0.75)

    def test_parse_duration_seconds_supports_clock_formats(self):
        self.assertEqual(parse_duration_seconds("00:45"), 45.0)
        self.assertEqual(parse_duration_seconds("01:02:03"), 3723.0)

    def test_compute_rotation_deadline_applies_lead_time(self):
        deadline = compute_rotation_deadline("50s", now=100.0, lead_seconds=4.0)
        self.assertEqual(deadline, 146.0)

    def test_should_rotate_now_waits_for_idle_state(self):
        decision = should_rotate_now(
            now=100.0,
            deadline=140.0,
            is_speaking=False,
            playback_backlog=0,
            tool_calls_in_flight=1,
            has_partial_turn=False,
            last_user_audio_at=98.0,
            idle_window_seconds=0.9,
        )

        self.assertFalse(decision)

    def test_should_rotate_now_allows_idle_rotation_before_deadline(self):
        decision = should_rotate_now(
            now=100.0,
            deadline=140.0,
            is_speaking=False,
            playback_backlog=0,
            tool_calls_in_flight=0,
            has_partial_turn=False,
            last_user_audio_at=98.0,
            idle_window_seconds=0.9,
        )

        self.assertTrue(decision)

    def test_should_rotate_now_forces_rotation_at_deadline(self):
        decision = should_rotate_now(
            now=140.0,
            deadline=140.0,
            is_speaking=True,
            playback_backlog=3,
            tool_calls_in_flight=2,
            has_partial_turn=True,
            last_user_audio_at=139.8,
            idle_window_seconds=0.9,
        )

        self.assertTrue(decision)


if __name__ == "__main__":
    unittest.main()
