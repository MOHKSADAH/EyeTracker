import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.tracker import FatigueScorer


def make() -> FatigueScorer:
    return FatigueScorer()


# ── Alert levels ────────────────────────────────────────────────────────────

class TestAlertLevels:
    def test_zero_score_is_level_0(self):
        s = make()
        state = s.update(0.0, 0.0, face_detected=False)
        assert state.alert_level == 0

    def test_score_50_is_level_1(self):
        s = make()
        s._score = 50.0
        assert s.update(0.0, 0.0, face_detected=False).alert_level == 1

    def test_score_79_is_level_1(self):
        s = make()
        s._score = 79.9
        assert s.update(0.0, 0.0, face_detected=False).alert_level == 1

    def test_score_80_is_level_2(self):
        s = make()
        s._score = 80.0
        assert s.update(0.0, 0.0, face_detected=False).alert_level == 2

    def test_score_100_is_level_3(self):
        s = make()
        s._score = 100.0
        assert s.update(0.0, 0.0, face_detected=False).alert_level == 3


# ── Blink detection ─────────────────────────────────────────────────────────

class TestBlinkDetection:
    def test_closed_below_threshold(self):
        s = make()
        s._open_eye_ratio = 1.0
        assert s.update(0.5, 1.0).is_closed is True

    def test_open_above_threshold(self):
        s = make()
        s._open_eye_ratio = 1.0
        assert s.update(0.9, 1.0).is_closed is False

    def test_at_threshold_is_open(self):
        s = make()
        s._open_eye_ratio = 1.0
        # 0.7 / 1.0 = 0.7, not < 0.7, so open
        assert s.update(0.7, 1.0).is_closed is False


# ── EMA baseline ────────────────────────────────────────────────────────────

class TestEMABaseline:
    def test_first_ratio_sets_baseline(self):
        s = make()
        s.update(0.5, 0.0)
        assert s._open_eye_ratio == pytest.approx(0.5)

    def test_higher_ratio_updates_baseline(self):
        s = make()
        s._open_eye_ratio = 0.5
        s.update(0.6, 0.1)   # 0.6 > 0.5 * 0.85 → updates
        assert s._open_eye_ratio > 0.5

    def test_low_ratio_does_not_update_baseline(self):
        s = make()
        s._open_eye_ratio = 1.0
        s.update(0.5, 0.1)   # 0.5 < 1.0 * 0.85 → no update
        assert s._open_eye_ratio == pytest.approx(1.0)


# ── Scoring points ───────────────────────────────────────────────────────────

class TestScoringPoints:
    def test_blink_rate_under_7(self):
        s = make()
        s._open_eye_ratio = 1.0
        now = 100.0
        s._closed_events = [(now - i, 0.1) for i in range(5)]
        assert s.update(0.9, now + 1).blink_rate_pts == 10

    def test_blink_rate_7_to_9(self):
        s = make()
        s._open_eye_ratio = 1.0
        now = 100.0
        s._closed_events = [(now - i, 0.1) for i in range(8)]
        assert s.update(0.9, now + 1).blink_rate_pts == 5

    def test_blink_rate_10_plus(self):
        s = make()
        s._open_eye_ratio = 1.0
        now = 100.0
        s._closed_events = [(now - i, 0.1) for i in range(12)]
        assert s.update(0.9, now + 1).blink_rate_pts == 0

    def test_heavy_eyes_pts(self):
        s = make()
        s._open_eye_ratio = 1.0
        now = 100.0
        # 2 long closures (> 0.4 s) = 2 × 3 = 6 pts
        s._closed_events = [(now - 1, 0.5), (now - 2, 0.6), (now - 3, 0.1)]
        assert s.update(0.9, now + 1).heavy_eyes_pts == 6

    def test_staring_pts(self):
        s = make()
        s._open_eye_ratio = 1.0
        now = 100.0
        # 1 stare ≥ 6 s = 4 pts; 1 short stare = 0
        s._open_events = [(now - 1, 7.0), (now - 2, 3.0)]
        assert s.update(0.9, now + 1).staring_pts == 4


# ── Event window pruning ─────────────────────────────────────────────────────

class TestEventPruning:
    def test_old_events_removed(self):
        s = make()
        s._open_eye_ratio = 1.0
        now = 200.0
        s._closed_events = [(now - 70, 0.5), (now - 5, 0.5)]
        s.update(0.9, now)
        assert len(s._closed_events) == 1

    def test_recent_events_kept(self):
        s = make()
        s._open_eye_ratio = 1.0
        now = 200.0
        s._closed_events = [(now - 10, 0.5), (now - 20, 0.5)]
        s.update(0.9, now)
        assert len(s._closed_events) == 2


# ── Score accumulation ───────────────────────────────────────────────────────

class TestScoreAccumulation:
    def test_accumulates_after_60s(self):
        s = make()
        s._open_eye_ratio = 1.0
        s.update(0.9, 0.0)                    # initialise last_score_time = 0
        s._closed_events = [(1.0, 0.5)]       # 1 heavy eye event → 3 pts
        s.update(0.9, 60.5)
        assert s._score > 0

    def test_no_accumulation_before_60s(self):
        s = make()
        s._open_eye_ratio = 1.0
        s.update(0.9, 0.0)
        s._closed_events = [(1.0, 0.5)]
        s.update(0.9, 30.0)
        assert s._score == 0.0


# ── New alert flag ────────────────────────────────────────────────────────────

class TestNewAlert:
    def test_new_alert_on_first_escalation(self):
        s = make()
        s._score = 50.0
        assert s.update(0.0, 0.0, face_detected=False).new_alert is True

    def test_no_new_alert_on_same_level(self):
        s = make()
        s._score = 50.0
        s.update(0.0, 0.0, face_detected=False)
        assert s.update(0.0, 1.0, face_detected=False).new_alert is False

    def test_new_alert_when_level_escalates(self):
        s = make()
        s._score = 50.0
        s.update(0.0, 0.0, face_detected=False)   # level 1
        s._score = 80.0
        assert s.update(0.0, 1.0, face_detected=False).new_alert is True


# ── Level 3 countdown ────────────────────────────────────────────────────────

class TestLockCountdown:
    def test_countdown_starts_at_15(self):
        s = make()
        s._score = 100.0
        state = s.update(0.0, 0.0, face_detected=False)
        assert state.lock_countdown == pytest.approx(15.0)

    def test_countdown_decreases(self):
        s = make()
        s._score = 100.0
        s.update(0.0, 0.0, face_detected=False)
        state = s.update(0.0, 5.0, face_detected=False)
        assert state.lock_countdown == pytest.approx(10.0)

    def test_score_resets_at_zero(self):
        s = make()
        s._score = 100.0
        s.update(0.0, 0.0, face_detected=False)
        state = s.update(0.0, 15.0, face_detected=False)
        assert s._score == 0.0
        assert state.alert_level == 0


# ── reset() ──────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_state(self):
        s = make()
        s._score = 75.0
        s._closed_events = [(1.0, 0.5)]
        s._open_eye_ratio = 0.8
        s.reset()
        assert s._score == 0.0
        assert s._closed_events == []
        assert s._open_eye_ratio is None
