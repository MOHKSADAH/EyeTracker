import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from dataclasses import dataclass
from typing import Optional, List, Tuple


@dataclass
class EyeState:
    score: float
    alert_level: int          # 0-3
    new_alert: bool           # True on the frame when alert_level first escalates
    blink_count: int          # blinks in last 60 s
    eye_ratio: float          # current openness relative to baseline (0-1+)
    is_closed: bool
    seconds_until_update: float
    blink_rate_pts: int
    heavy_eyes_pts: int
    staring_pts: int
    lock_countdown: Optional[float]  # seconds left before auto-reset (level 3 only)
    face_detected: bool


class FatigueScorer:
    """Pure scoring logic — no MediaPipe, no camera. Fully testable in isolation."""

    BLINK_THRESHOLD = 0.7
    EMA_ALPHA = 0.05
    WINDOW_SECONDS = 60.0
    LOCK_COUNTDOWN = 15.0

    def __init__(self):
        self._open_eye_ratio: Optional[float] = None
        self._closed_events: List[Tuple[float, float]] = []
        self._open_events: List[Tuple[float, float]] = []
        self._prev_closed = False
        self._closed_start: Optional[float] = None
        self._open_start: Optional[float] = None
        self._score = 0.0
        self._last_score_time: Optional[float] = None
        self._alerted_level = 0
        self._level3_start: Optional[float] = None

    def update(self, ratio: float, now: float, face_detected: bool = True) -> EyeState:
        if self._last_score_time is None:
            self._last_score_time = now

        eye_ratio = 0.0
        is_closed = False
        blink_rate_pts = 0
        heavy_eyes_pts = 0
        staring_pts = 0

        if face_detected and ratio > 0:
            if self._open_eye_ratio is None:
                self._open_eye_ratio = ratio
            elif ratio > self._open_eye_ratio * 0.85:
                self._open_eye_ratio = (
                    (1 - self.EMA_ALPHA) * self._open_eye_ratio + self.EMA_ALPHA * ratio
                )

            openness = ratio / self._open_eye_ratio if self._open_eye_ratio > 0 else 0.0
            eye_ratio = openness
            closed = openness < self.BLINK_THRESHOLD
            is_closed = closed

            if closed and not self._prev_closed:
                self._closed_start = now
                if self._open_start is not None:
                    self._open_events.append((now, now - self._open_start))
                    self._open_start = None
            elif not closed and self._prev_closed:
                if self._closed_start is not None:
                    self._closed_events.append((now, now - self._closed_start))
                    self._closed_start = None
                self._open_start = now
            self._prev_closed = closed

            window_start = now - self.WINDOW_SECONDS
            self._closed_events = [(t, d) for (t, d) in self._closed_events if t >= window_start]
            self._open_events = [(t, d) for (t, d) in self._open_events if t >= window_start]

            blinks_now = len(self._closed_events)
            blink_rate_pts = 10 if blinks_now < 7 else (5 if blinks_now < 10 else 0)
            heavy_eyes_pts = sum(1 for (_, d) in self._closed_events if d > 0.4) * 3
            staring_pts = sum(1 for (_, d) in self._open_events if d >= 6.0) * 4
            current_minute_pts = blink_rate_pts + heavy_eyes_pts + staring_pts

            if now - self._last_score_time >= self.WINDOW_SECONDS:
                self._score += current_minute_pts
                self._last_score_time = now

        level = (
            3 if self._score >= 100.0 else
            2 if self._score >= 80.0 else
            1 if self._score >= 50.0 else
            0
        )

        lock_countdown: Optional[float] = None
        if level == 3:
            if self._level3_start is None:
                self._level3_start = now
            remaining = max(0.0, self.LOCK_COUNTDOWN - (now - self._level3_start))
            lock_countdown = remaining
            if remaining == 0.0:
                self._score = 0.0
                self._alerted_level = 0
                self._level3_start = None
                level = 0
        elif self._level3_start is not None:
            self._level3_start = None

        new_alert = level > 0 and level > self._alerted_level
        if level > 0:
            self._alerted_level = max(self._alerted_level, level)
        if level == 0:
            self._alerted_level = 0

        seconds_until_update = max(0.0, self.WINDOW_SECONDS - (now - self._last_score_time))

        return EyeState(
            score=self._score,
            alert_level=level,
            new_alert=new_alert,
            blink_count=len(self._closed_events),
            eye_ratio=eye_ratio,
            is_closed=is_closed,
            seconds_until_update=seconds_until_update,
            blink_rate_pts=blink_rate_pts,
            heavy_eyes_pts=heavy_eyes_pts,
            staring_pts=staring_pts,
            lock_countdown=lock_countdown,
            face_detected=face_detected,
        )

    def reset(self) -> None:
        self._open_eye_ratio = None
        self._closed_events = []
        self._open_events = []
        self._prev_closed = False
        self._closed_start = None
        self._open_start = None
        self._score = 0.0
        self._last_score_time = None
        self._alerted_level = 0
        self._level3_start = None


class EyeTrackerCore:
    """Full eye tracker with MediaPipe face landmark detection."""

    def __init__(self, model_path: str):
        self._scorer = FatigueScorer()
        opts = python.BaseOptions(model_asset_path=model_path)
        face_opts = vision.FaceLandmarkerOptions(
            base_options=opts,
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
        )
        self._detector = vision.FaceLandmarker.create_from_options(face_opts)

    def process_frame(self, frame: np.ndarray, timestamp_ms: int) -> EyeState:
        rgb = frame[:, :, ::-1].copy()  # BGR -> RGB without cv2 import
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        res = self._detector.detect_for_video(mp_img, timestamp_ms)

        now = timestamp_ms / 1000.0
        ratio = 0.0
        face_detected = bool(res.face_landmarks)

        if face_detected:
            lm = res.face_landmarks[0]
            face_dist = float(np.hypot(lm[468].x - lm[473].x, lm[468].y - lm[473].y))
            eye_open = float(np.hypot(lm[159].x - lm[145].x, lm[159].y - lm[145].y))
            ratio = eye_open / face_dist if face_dist > 0 else 0.0

        return self._scorer.update(ratio, now, face_detected)

    def reset(self) -> None:
        self._scorer.reset()
