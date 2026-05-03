# EyeTracker

Real-time fatigue detection using webcam + MediaPipe face landmarks.

## What It Does

Tracks eye blink rate, closure duration, and staring patterns to compute a fatigue score (0–100+) over rolling 60-second windows. Progressive alerts appear at score thresholds 50 / 80 / 100.

## Quick Start

### Web service (recommended)
```
pip install -r requirements.txt
uvicorn server.main:app --reload
```
Open http://localhost:8000 — allow camera access — monitoring begins.

### Standalone desktop script
```
python EyeTracker.py               # live webcam
python EyeTracker.py --video clip.mp4  # test with a video file
```

### Docker
```
docker compose up
```
Open http://localhost:8000.

## Architecture

```
Browser
  getUserMedia() → webcam JPEG frames (~10 fps)
  WebSocket /ws  → FastAPI server
  JSON response  → HUD overlay + alert overlay rendered in browser

FastAPI  (server/main.py)
  /ws             WebSocket — receives frames, returns EyeState JSON
  /process-video  POST — accepts video file, returns per-frame analysis
  /               Serves static HTML/JS/CSS

EyeTrackerCore  (core/tracker.py)
  FatigueScorer   Pure math/state — testable without MediaPipe
  EyeTrackerCore  Wraps MediaPipe face landmark detection
```

## Scoring Algorithm

Every 60 seconds, points are accumulated into a running total:

| Signal | Condition | Points |
|---|---|---|
| Blink rate | < 7 blinks/min | 10 |
| Blink rate | 7–9 blinks/min | 5 |
| Blink rate | ≥ 10 blinks/min | 0 |
| Heavy eyes | Each blink > 0.4 s | 3 |
| Staring | Each open period ≥ 6 s | 4 |

Alert thresholds: Level 1 ≥ 50, Level 2 ≥ 80, Level 3 ≥ 100 (15 s countdown then auto-reset).

## Configuration

All constants live in `FatigueScorer` in [core/tracker.py](core/tracker.py):

| Constant | Default | Meaning |
|---|---|---|
| `BLINK_THRESHOLD` | 0.7 | Eye openness below 70 % of baseline = closed |
| `EMA_ALPHA` | 0.05 | Baseline smoothing factor |
| `WINDOW_SECONDS` | 60.0 | Rolling window duration |
| `LOCK_COUNTDOWN` | 15.0 | Seconds before auto-reset at level 3 |

## Running Tests

```
pytest tests/test_scoring.py -v     # unit tests — no camera or model needed
pytest tests/test_video.py -v       # integration tests — model is mocked
pytest -v                           # all tests
```

## Model File

MediaPipe `face_landmarker.task` (~32 MB) is auto-downloaded on first run to `models/`.
The `models/` directory is gitignored. The Dockerfile downloads it at build time.

## Key Files

| Path | Purpose |
|---|---|
| `EyeTracker.py` | Standalone desktop script (cv2 HUD, Windows screen lock) |
| `core/tracker.py` | `FatigueScorer` + `EyeTrackerCore` |
| `core/model_manager.py` | Auto-download model utility |
| `server/main.py` | FastAPI app (WebSocket + REST + static files) |
| `server/static/` | Browser frontend (HTML/JS/CSS) |
| `tests/` | pytest test suite |
