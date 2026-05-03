# EyeTracker

Real-time driver/user fatigue detection via webcam. Uses MediaPipe face landmarks to track blink rate, eye closure duration, and staring patterns. Computes a rolling fatigue score and shows progressive alerts in the browser.

<img width="2319" height="1312" alt="EYETRACJER" src="https://github.com/user-attachments/assets/18580afb-32b0-4dc8-9dfb-98f04c7e6f48" />

---

## Table of Contents

- [How It Works](#how-it-works)
- [Requirements](#requirements)
- [Option A — Web Service (recommended)](#option-a--web-service-recommended)
- [Option B — Standalone Desktop Script](#option-b--standalone-desktop-script)
- [Option C — Docker](#option-c--docker)
- [Deploying to Render](#deploying-to-render)
- [Running Tests](#running-tests)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

---

## How It Works

Every 60 seconds, the system scores your current window:

| Signal     | Condition                  | Points |
| ---------- | -------------------------- | ------ |
| Blink rate | < 7 blinks/min             | 10     |
| Blink rate | 7–9 blinks/min             | 5      |
| Blink rate | ≥ 10 blinks/min            | 0      |
| Heavy eyes | Each blink lasting > 0.4 s | 3      |
| Staring    | Each open period ≥ 6 s     | 4      |

Points accumulate into a running total. Alerts trigger at:

| Score | Level    | Action                                             |
| ----- | -------- | -------------------------------------------------- |
| ≥ 50  | Mild     | Orange overlay + browser notification              |
| ≥ 80  | Moderate | Red overlay                                        |
| ≥ 100 | Severe   | Deep red overlay + 15 s countdown, then auto-reset |

On Windows + standalone script, level 3 also locks the screen.

---

## Requirements

| Requirement | Version                      |
| ----------- | ---------------------------- |
| Python      | 3.9 or newer                 |
| pip         | any recent version           |
| Webcam      | required for live monitoring |
| OS          | Windows / macOS / Linux      |

> The MediaPipe model file (~32 MB) is downloaded automatically on first run. You do not need to download it manually.

---

## Option A — Web Service (recommended)

The browser captures your webcam, sends frames to the local server, and renders the HUD + alerts.

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the server

```bash
uvicorn server.main:app --reload
```

The first time you run this, it will download the MediaPipe model (~32 MB). This only happens once.

### 3. Open the app

Go to **http://localhost:8000** in your browser, click **Start Monitoring**, and allow camera access.

That's it. The HUD appears and fatigue monitoring begins.

---

## Option B — Standalone Desktop Script

A single-file script that uses OpenCV to display the HUD directly on screen. No browser needed. On Windows it can lock your screen at severe fatigue.

### Live webcam

```bash
python EyeTracker.py
```

### Test with a video file

```bash
python EyeTracker.py --video path/to/clip.mp4
```

Press `q` to quit.

---

## Option C — Docker

No Python installation needed. Docker handles everything including the model download at build time.

### Build and run

```bash
docker compose up
```

First build takes a few minutes (downloads Python packages + the 32 MB model). Subsequent starts are fast.

Open **http://localhost:8000**.

### Stop

```bash
docker compose down
```

---

## Deploying to Render

> **Critical:** Browsers only allow camera access on `localhost` or over **HTTPS**. Any cloud deployment must serve the app over HTTPS or the webcam will not work.

### What you need

1. A GitHub repository containing this project
2. A Render account
3. HTTPS/TLS, which Render provides automatically

### Deploy to Render

1. Push to GitHub
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Set **Runtime** to Docker
5. Render builds and deploys automatically; it will use the `Dockerfile` in this repo
6. Render provides a free `*.onrender.com` HTTPS URL

### Notes for Render

- The container listens on Render's `PORT` environment variable, so you do not need to hardcode a port in the service settings.
- Keep the service as one app: the FastAPI backend serves the HTML, JavaScript, CSS, WebSocket endpoint, and upload API from the same origin.
- Free Render services may sleep when idle, so the first request after inactivity can be slow.

### If you want a different host later

```bash
# On your server:
git clone https://github.com/you/EyeTracker.git
cd EyeTracker
docker compose up -d

# Set up nginx reverse proxy + Let's Encrypt (certbot)
# Point your domain to the server IP
# nginx proxies HTTPS → http://localhost:8000
```

A minimal nginx config:

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

> The `Upgrade` and `Connection` headers are required for WebSocket proxying.

---

## Running Tests

No camera or model file required — the tests mock all external dependencies.

```bash
# Unit tests (scoring logic, alert levels, EMA, etc.)
pytest tests/test_scoring.py -v

# Integration tests (video endpoint with mocked tracker)
pytest tests/test_video.py -v

# All tests
pytest -v
```

Expected output: **30 passed**.

### Testing with a real video file

```bash
python EyeTracker.py --video your_clip.mp4
```

Or via the API:

```bash
curl -X POST http://localhost:8000/process-video \
  -F "file=@your_clip.mp4" | python -m json.tool
```

Returns JSON with per-frame analysis and a final summary.

---

## Configuration

All tunable constants are class-level attributes in `FatigueScorer` inside [core/tracker.py](core/tracker.py):

```python
BLINK_THRESHOLD = 0.7   # eye openness below 70% of baseline = closed
EMA_ALPHA       = 0.05  # how fast the baseline adapts (lower = slower)
WINDOW_SECONDS  = 60.0  # rolling window for event tracking
LOCK_COUNTDOWN  = 15.0  # seconds before score resets at level 3
```

Frame capture rate (web only) is set in [server/static/app.js](server/static/app.js):

```javascript
setInterval(captureAndSend, 100); // 100 ms = ~10 fps
```

---

## Project Structure

```
EyeTracker/
├── EyeTracker.py            Standalone desktop script (cv2 HUD, --video flag)
├── requirements.txt         Python dependencies
├── Dockerfile
├── docker-compose.yml
│
├── core/
│   ├── tracker.py           FatigueScorer + EyeTrackerCore classes
│   └── model_manager.py     Auto-download face_landmarker.task
│
├── server/
│   ├── main.py              FastAPI app (WebSocket /ws, POST /process-video)
│   └── static/
│       ├── index.html       Single-page UI
│       ├── app.js           Webcam capture, WebSocket client, HUD, alerts
│       └── style.css        HUD + alert overlay styles
│
├── tests/
│   ├── test_scoring.py      27 unit tests — no camera needed
│   └── test_video.py        3 integration tests — model mocked
│
└── models/                  gitignored — model downloaded here on first run
    └── face_landmarker.task
```

---

## Troubleshooting

**Camera not working in browser**

- You must be on `http://localhost` or `https://`. Any other HTTP origin blocks camera access — this is enforced by the browser, not the app.
- Check that no other tab or app is using the camera.

**"Model not found" or download fails**

```bash
python -c "from core.model_manager import ensure_model; ensure_model()"
```

This downloads the model manually. If it fails due to network issues, download the file directly:

```
https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
```

Save it to `models/face_landmarker.task` in the project root.

**WebSocket disconnects immediately**

Make sure the server is running (`uvicorn server.main:app --reload`) before opening the browser.

**Docker build fails on ARM (Apple Silicon)**

MediaPipe's pre-built wheels support `linux/amd64`. Add a platform flag:

```bash
docker compose build --platform linux/amd64
docker compose up
```

**Score never increases**

The score only accumulates once every 60 seconds. Watch the "Next Update" countdown in the HUD. The "Live Analytics" values show what _will_ be added at the next tick.

**Alerts appear but disappear instantly**

This is expected for levels 1 and 2 — the overlay stays visible as long as the score is above the threshold. If the score resets (level 3 countdown reached zero), the overlay clears automatically.
