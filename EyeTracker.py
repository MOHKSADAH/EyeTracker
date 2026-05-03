import cv2
import numpy as np
import time
import os
import platform
import argparse
import urllib.request
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

IS_WINDOWS = platform.system() == 'Windows'
if IS_WINDOWS:
    import ctypes

# --- Model setup (auto-download if missing) ---
MODEL_URL = (
    'https://storage.googleapis.com/mediapipe-models/'
    'face_landmarker/face_landmarker/float16/1/face_landmarker.task'
)
MODEL_FILENAME = 'face_landmarker.task'

def _ensure_model() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    models_dir = os.path.join(script_dir, 'models')
    os.makedirs(models_dir, exist_ok=True)
    path = os.path.join(models_dir, MODEL_FILENAME)
    if not os.path.exists(path):
        print(f'Downloading model to {path} ...')
        def _progress(count, block_size, total):
            if total > 0:
                print(f'\r  {min(100, count * block_size * 100 // total)}%', end='', flush=True)
        urllib.request.urlretrieve(MODEL_URL, path, reporthook=_progress)
        print()
    return path

MODEL_PATH = _ensure_model()

opts = python.BaseOptions(model_asset_path=MODEL_PATH)
face_opts = vision.FaceLandmarkerOptions(
    base_options=opts,
    running_mode=vision.RunningMode.VIDEO,
    num_faces=1,
)
detector = vision.FaceLandmarker.create_from_options(face_opts)

# --- State ---
open_eye_ratio = None
ema_alpha = 0.05
blink_threshold = 0.7
window_seconds = 60.0
closed_events = []
open_events = []
prev_closed = False
closed_start = None
open_start = None

score = 0.0
last_score_time = time.time()
alerted_level = 0

alert_active = False
alert_start_time = 0.0
ALERT_DURATION = 10.0


def windows_lock():
    if IS_WINDOWS:
        try:
            ctypes.windll.user32.LockWorkStation()
        except Exception as e:
            print(f'Lock error: {e}')


def show_alert(text: str):
    global alert_active, alert_start_time
    print(f'[ALERT] {text}')
    if IS_WINDOWS:
        aw, ah = 600, 140
        img = np.zeros((ah, aw, 3), dtype=np.uint8)
        img[:] = (0, 165, 255)
        cv2.putText(img, text, (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)
        try:
            cv2.namedWindow('Alert', cv2.WINDOW_AUTOSIZE)
            cv2.imshow('Alert', img)
            hwnd = ctypes.windll.user32.FindWindowW(None, 'Alert')
            if hwnd:
                ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
        except Exception:
            pass
    if not alert_active:
        alert_active = True
        alert_start_time = time.time()


def get_dist(a, b):
    return np.hypot(a.x - b.x, a.y - b.y)


# --- Entry point ---
parser = argparse.ArgumentParser(description='EyeTracker fatigue detection')
parser.add_argument('--video', metavar='PATH', help='Path to video file (default: webcam)')
args = parser.parse_args()

source = args.video if args.video else 0
cap = cv2.VideoCapture(source)
start_time = time.time()

print("Running... press 'q' to quit.")

while cap.isOpened():
    ok, frame = cap.read()
    if not ok:
        break
    if args.video is None:
        frame = cv2.flip(frame, 1)
    now = time.time()

    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    ts = int((now - start_time) * 1000)
    res = detector.detect_for_video(mp_img, ts)

    if res.face_landmarks:
        for lm in res.face_landmarks:
            face_dist = get_dist(lm[468], lm[473])
            eye_open = get_dist(lm[159], lm[145])
            ratio = eye_open / face_dist if face_dist > 0 else 0

            if open_eye_ratio is None:
                open_eye_ratio = ratio
            if ratio > open_eye_ratio * 0.85:
                open_eye_ratio = (1 - ema_alpha) * open_eye_ratio + ema_alpha * ratio

            openness = ratio / open_eye_ratio if open_eye_ratio > 0 else 0
            closed = openness < blink_threshold

            if closed and not prev_closed:
                closed_start = now
                if open_start is not None:
                    open_events.append((now, now - open_start))
                    open_start = None
            elif not closed and prev_closed:
                if closed_start is not None:
                    closed_events.append((now, now - closed_start))
                    closed_start = None
                open_start = now
            prev_closed = closed

            window_start = now - window_seconds
            closed_events = [(t, d) for (t, d) in closed_events if t >= window_start]
            open_events = [(t, d) for (t, d) in open_events if t >= window_start]

            blinks_now = len(closed_events)
            b_pts_live = 10 if blinks_now < 7 else (5 if blinks_now < 10 else 0)
            c_pts_live = sum(1 for (_, d) in closed_events if d > 0.4) * 3
            o_pts_live = sum(1 for (_, d) in open_events if d >= 6.0) * 4
            current_minute_pts = b_pts_live + c_pts_live + o_pts_live

            if now - last_score_time >= 60.0:
                score += current_minute_pts
                last_score_time = now

            level = 3 if score >= 100.0 else (2 if score >= 80.0 else (1 if score >= 50.0 else 0))
            if level > 0 and not alert_active and level > alerted_level:
                if level == 3:
                    show_alert('Danger: severe fatigue! Resetting in 15 seconds')
                    time.sleep(15)
                    windows_lock()
                    score = 0.0
                    alerted_level = 0
                elif level == 2:
                    show_alert('Moderate fatigue: please take a break')
                    alerted_level = 2
                elif level == 1:
                    show_alert('Mild fatigue: take a short rest')
                    alerted_level = 1
            if level == 0:
                alerted_level = 0

            cv2.putText(frame, f'TOTAL SCORE: {score:.0f}/100', (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 215, 255), 2)
            cv2.rectangle(frame, (10, 60), (280, 185), (0, 0, 0), -1)
            cv2.putText(frame, 'LIVE ANALYTICS:', (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, f'Blink Rate Pts: {b_pts_live}', (25, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.putText(frame, f'Heavy Eyes Pts: {c_pts_live}', (25, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.putText(frame, f'Staring Pts:    {o_pts_live}', (25, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.putText(frame, f'Blinks in 60s:  {blinks_now}', (25, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

            time_rem = max(0, int(60 - (now - last_score_time)))
            cv2.putText(frame, f'Next Points Update in: {time_rem}s', (10, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    cv2.imshow('Fatigue Control Center', frame)

    if alert_active and (time.time() - alert_start_time) > ALERT_DURATION:
        if IS_WINDOWS:
            try:
                cv2.destroyWindow('Alert')
                for _ in range(5):
                    cv2.waitKey(1)
            except Exception:
                pass
        alert_active = False

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
