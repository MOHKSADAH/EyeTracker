"""Integration tests for the /process-video endpoint.

EyeTrackerCore and ensure_model are mocked so no model file or camera is needed.
"""
import os
import sys
import tempfile
import pytest
import numpy as np
import cv2
from unittest.mock import patch
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.tracker import EyeState


def _mock_state() -> EyeState:
    return EyeState(
        score=5.0, alert_level=0, new_alert=False,
        blink_count=3, eye_ratio=0.9, is_closed=False,
        seconds_until_update=45.0, blink_rate_pts=10,
        heavy_eyes_pts=0, staring_pts=0,
        lock_countdown=None, face_detected=True,
    )


def _make_video(path: str, frames: int = 10, fps: int = 10) -> None:
    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
    out = cv2.VideoWriter(path, fourcc, fps, (320, 240))
    for _ in range(frames):
        out.write(np.zeros((240, 320, 3), dtype=np.uint8))
    out.release()


def _get_client():
    """Return a TestClient with mocked dependencies."""
    from fastapi.testclient import TestClient
    import server.main as main_mod

    with patch('server.main.ensure_model', return_value='/fake/model.task'), \
         patch('server.main.EyeTrackerCore') as MockCore:
        MockCore.return_value.process_frame.return_value = _mock_state()
        # Reload so lifespan picks up the mock
        import importlib
        importlib.reload(main_mod)
        client = TestClient(main_mod.app)
        return client, main_mod


def test_process_video_status_200():
    from fastapi.testclient import TestClient
    import server.main as main_mod
    import importlib

    with patch('server.main.ensure_model', return_value='/fake/model.task'), \
         patch('server.main.EyeTrackerCore') as MockCore:
        MockCore.return_value.process_frame.return_value = _mock_state()
        importlib.reload(main_mod)

        with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as f:
            tmp = f.name
        try:
            _make_video(tmp)
            with TestClient(main_mod.app) as client:
                with open(tmp, 'rb') as f:
                    resp = client.post('/process-video', files={'file': ('test.avi', f, 'video/x-msvideo')})
            assert resp.status_code == 200
        finally:
            os.unlink(tmp)


def test_process_video_response_structure():
    from fastapi.testclient import TestClient
    import server.main as main_mod
    import importlib

    with patch('server.main.ensure_model', return_value='/fake/model.task'), \
         patch('server.main.EyeTrackerCore') as MockCore:
        MockCore.return_value.process_frame.return_value = _mock_state()
        importlib.reload(main_mod)

        with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as f:
            tmp = f.name
        try:
            _make_video(tmp, frames=5)
            with TestClient(main_mod.app) as client:
                with open(tmp, 'rb') as f:
                    resp = client.post('/process-video', files={'file': ('test.avi', f, 'video/x-msvideo')})
            data = resp.json()
            assert 'frames_processed' in data
            assert 'final_score' in data
            assert 'final_alert_level' in data
            assert 'total_blinks' in data
            assert 'frames' in data
            assert data['frames_processed'] > 0
        finally:
            os.unlink(tmp)


def test_process_video_frame_fields():
    from fastapi.testclient import TestClient
    import server.main as main_mod
    import importlib

    with patch('server.main.ensure_model', return_value='/fake/model.task'), \
         patch('server.main.EyeTrackerCore') as MockCore:
        MockCore.return_value.process_frame.return_value = _mock_state()
        importlib.reload(main_mod)

        with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as f:
            tmp = f.name
        try:
            _make_video(tmp, frames=3)
            with TestClient(main_mod.app) as client:
                with open(tmp, 'rb') as f:
                    resp = client.post('/process-video', files={'file': ('test.avi', f, 'video/x-msvideo')})
            frame = resp.json()['frames'][0]
            for field in ('score', 'alert_level', 'blink_count', 'eye_ratio', 'is_closed', 'face_detected'):
                assert field in frame, f"Missing field: {field}"
        finally:
            os.unlink(tmp)
