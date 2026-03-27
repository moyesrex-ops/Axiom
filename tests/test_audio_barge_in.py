import unittest

from core.audio_barge_in import BargeInDetector, InterruptTuning, synth_click_frame, synth_voice_like_frame


class AudioBargeInTests(unittest.TestCase):
    def test_single_click_does_not_trigger_barge_in(self):
        detector = BargeInDetector()

        analysis = detector.analyze(synth_click_frame())

        self.assertFalse(analysis.candidate)
        self.assertFalse(analysis.triggered)

    def test_sustained_voice_like_frames_trigger_barge_in(self):
        detector = BargeInDetector()
        detector.observe_idle_rms(90.0)

        triggered = []
        for _ in range(3):
            triggered.append(detector.analyze(synth_voice_like_frame(amplitude=3000.0)).triggered)

        self.assertEqual(triggered, [False, False, True])

    def test_loud_playback_requires_stronger_user_signal(self):
        detector = BargeInDetector()
        detector.observe_playback_rms(9000.0)

        results = [detector.analyze(synth_voice_like_frame(amplitude=1800.0)) for _ in range(3)]

        self.assertTrue(all(not item.candidate for item in results))
        self.assertTrue(all(not item.triggered for item in results))

    def test_custom_required_frames_are_respected(self):
        detector = BargeInDetector(
            InterruptTuning(required_speech_frames=2, history_frames=3)
        )

        first = detector.analyze(synth_voice_like_frame(amplitude=3000.0))
        second = detector.analyze(synth_voice_like_frame(amplitude=3000.0))

        self.assertFalse(first.triggered)
        self.assertTrue(second.triggered)


if __name__ == "__main__":
    unittest.main()
