from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

import numpy as np


@dataclass
class InterruptTuning:
    min_interrupt_rms: float = 850.0
    ambient_multiplier: float = 3.35
    playback_multiplier: float = 0.34
    min_speech_band_ratio: float = 0.42
    min_zero_crossing_ratio: float = 0.015
    max_zero_crossing_ratio: float = 0.24
    onset_multiplier: float = 1.12
    required_speech_frames: int = 3
    history_frames: int = 4
    ambient_alpha: float = 0.08
    playback_alpha: float = 0.28
    speaker_guard_min_rms: float = 360.0
    speaker_guard_ambient_multiplier: float = 2.2
    speaker_guard_playback_multiplier: float = 0.16
    speaker_guard_ms: int = 120


@dataclass
class FrameAnalysis:
    rms: float
    interrupt_threshold: float
    speech_band_ratio: float
    zero_crossing_ratio: float
    candidate: bool
    triggered: bool


def tuning_from_runtime(runtime: dict | None) -> InterruptTuning:
    runtime = runtime or {}
    audio = runtime.get("audio", {}) or {}
    interrupt = audio.get("interrupt", {}) or {}
    return InterruptTuning(
        min_interrupt_rms=float(interrupt.get("min_rms", 850.0) or 850.0),
        ambient_multiplier=float(interrupt.get("ambient_multiplier", 3.35) or 3.35),
        playback_multiplier=float(interrupt.get("playback_multiplier", 0.34) or 0.34),
        min_speech_band_ratio=float(interrupt.get("min_speech_band_ratio", 0.42) or 0.42),
        min_zero_crossing_ratio=float(interrupt.get("min_zero_crossing_ratio", 0.015) or 0.015),
        max_zero_crossing_ratio=float(interrupt.get("max_zero_crossing_ratio", 0.24) or 0.24),
        onset_multiplier=float(interrupt.get("onset_multiplier", 1.12) or 1.12),
        required_speech_frames=max(1, int(interrupt.get("required_speech_frames", 3) or 3)),
        history_frames=max(2, int(interrupt.get("history_frames", 4) or 4)),
        ambient_alpha=float(interrupt.get("ambient_alpha", 0.08) or 0.08),
        playback_alpha=float(interrupt.get("playback_alpha", 0.28) or 0.28),
        speaker_guard_min_rms=float(interrupt.get("speaker_guard_min_rms", 360.0) or 360.0),
        speaker_guard_ambient_multiplier=float(
            interrupt.get("speaker_guard_ambient_multiplier", 2.2) or 2.2
        ),
        speaker_guard_playback_multiplier=float(
            interrupt.get("speaker_guard_playback_multiplier", 0.16) or 0.16
        ),
        speaker_guard_ms=max(0, int(interrupt.get("speaker_guard_ms", 120) or 120)),
    )


def _frame_rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float32)))))


def _zero_crossing_ratio(samples: np.ndarray) -> float:
    if samples.size < 2:
        return 0.0
    signs = np.signbit(samples)
    crossings = np.count_nonzero(signs[1:] != signs[:-1])
    return float(crossings) / float(samples.size - 1)


def _speech_band_ratio(samples: np.ndarray, sample_rate: int) -> float:
    if samples.size < 64:
        return 0.0
    window = np.hanning(samples.size).astype(np.float32)
    weighted = samples.astype(np.float32) * window
    spectrum = np.fft.rfft(weighted)
    freqs = np.fft.rfftfreq(weighted.size, d=1.0 / float(sample_rate))
    power = np.abs(spectrum) ** 2

    total_mask = (freqs >= 80.0) & (freqs <= 5000.0)
    speech_mask = (freqs >= 120.0) & (freqs <= 3200.0)
    total_energy = float(np.sum(power[total_mask]))
    if total_energy <= 1e-6:
        return 0.0
    speech_energy = float(np.sum(power[speech_mask]))
    return speech_energy / total_energy


def pcm_chunk_rms(chunk: bytes | bytearray | memoryview) -> float:
    if not chunk:
        return 0.0
    samples = np.frombuffer(chunk, dtype=np.int16)
    return _frame_rms(samples)


class BargeInDetector:
    def __init__(self, tuning: InterruptTuning | None = None):
        self.tuning = tuning or InterruptTuning()
        self.ambient_rms = 120.0
        self.playback_rms = 0.0
        self._previous_rms = 0.0
        self._history = deque(maxlen=max(self.tuning.history_frames, self.tuning.required_speech_frames))

    def reset(self) -> None:
        self._previous_rms = 0.0
        self._history.clear()

    def interrupt_threshold(self) -> float:
        return max(
            self.tuning.min_interrupt_rms,
            self.ambient_rms * self.tuning.ambient_multiplier,
            self.playback_rms * self.tuning.playback_multiplier,
        )

    def speaker_guard_threshold(self) -> float:
        return max(
            self.tuning.speaker_guard_min_rms,
            self.ambient_rms * self.tuning.speaker_guard_ambient_multiplier,
            self.playback_rms * self.tuning.speaker_guard_playback_multiplier,
        )

    def speaker_guard_seconds(self) -> float:
        return float(self.tuning.speaker_guard_ms) / 1000.0

    def observe_idle_rms(self, rms: float) -> None:
        rms = max(float(rms), 50.0)
        alpha = min(max(self.tuning.ambient_alpha, 0.01), 0.5)
        self.ambient_rms = (self.ambient_rms * (1.0 - alpha)) + (rms * alpha)

    def observe_playback_rms(self, rms: float) -> None:
        rms = max(float(rms), 0.0)
        alpha = min(max(self.tuning.playback_alpha, 0.01), 0.6)
        smoothed = (self.playback_rms * (1.0 - alpha)) + (rms * alpha)
        self.playback_rms = max(rms, smoothed)

    def observe_playback_chunk(self, chunk: bytes | bytearray | memoryview) -> float:
        rms = pcm_chunk_rms(chunk)
        self.observe_playback_rms(rms)
        return rms

    def analyze(self, samples: np.ndarray, sample_rate: int = 16000) -> FrameAnalysis:
        rms = _frame_rms(samples)
        threshold = self.interrupt_threshold()
        zcr = _zero_crossing_ratio(samples)
        speech_ratio = _speech_band_ratio(samples, sample_rate)
        recent_activity = any(self._history)
        onset_ok = recent_activity or rms >= max(self._previous_rms * self.tuning.onset_multiplier, threshold * 0.92)
        candidate = (
            rms >= threshold
            and speech_ratio >= self.tuning.min_speech_band_ratio
            and self.tuning.min_zero_crossing_ratio <= zcr <= self.tuning.max_zero_crossing_ratio
            and onset_ok
        )

        self._history.append(bool(candidate))
        triggered = False
        if len(self._history) >= self.tuning.required_speech_frames:
            triggered = sum(1 for item in self._history if item) >= self.tuning.required_speech_frames

        self._previous_rms = rms
        if triggered:
            self.reset()

        return FrameAnalysis(
            rms=rms,
            interrupt_threshold=threshold,
            speech_band_ratio=speech_ratio,
            zero_crossing_ratio=zcr,
            candidate=bool(candidate),
            triggered=bool(triggered),
        )


def synth_voice_like_frame(
    amplitude: float = 2400.0,
    sample_rate: int = 16000,
    samples: int = 1024,
    freqs: Iterable[float] = (220.0, 440.0, 660.0),
) -> np.ndarray:
    timeline = np.arange(samples, dtype=np.float32) / float(sample_rate)
    signal = np.zeros(samples, dtype=np.float32)
    for index, freq in enumerate(freqs):
        weight = 1.0 / float(index + 1)
        signal += np.sin(2.0 * np.pi * float(freq) * timeline) * weight
    signal /= max(np.max(np.abs(signal)), 1.0)
    return np.clip(signal * float(amplitude), -32768, 32767).astype(np.int16)


def synth_click_frame(amplitude: float = 12000.0, samples: int = 1024) -> np.ndarray:
    frame = np.zeros(samples, dtype=np.int16)
    if samples:
        frame[samples // 2] = int(max(min(amplitude, 32767.0), -32768.0))
    return frame
