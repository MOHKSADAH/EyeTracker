import os
import json
import asyncio
import tempfile
import time
from pathlib import Path
from contextlib import asynccontextmanager
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse

from core.tracker import EyeTrackerCore
from core.model_manager import ensure_model

_model_path: str = ""
_executor = ThreadPoolExecutor(max_workers=4)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model_path
    _model_path = ensure_model()
    yield


app = FastAPI(title="EyeTracker", lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    tracker = EyeTrackerCore(_model_path)
    loop = asyncio.get_event_loop()
    try:
        while True:
            data = await ws.receive_bytes()
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            timestamp_ms = int(time.time() * 1000)
            state = await loop.run_in_executor(
                _executor, tracker.process_frame, frame, timestamp_ms
            )
            await ws.send_json(asdict(state))
    except WebSocketDisconnect:
        pass


@app.post("/process-video")
async def process_video(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix if file.filename else ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(_executor, _process_video_sync, tmp_path)
    finally:
        os.unlink(tmp_path)

    return result


def _process_video_sync(video_path: str) -> dict:
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    tracker = EyeTrackerCore(_model_path)
    frames_data = []
    frame_num = 0

    while cap.isOpened():
        ok, frame = cap.read()
        if not ok:
            break
        timestamp_ms = int(frame_num * (1000.0 / fps))
        state = tracker.process_frame(frame, timestamp_ms)
        frames_data.append(asdict(state))
        frame_num += 1

    cap.release()

    last = frames_data[-1] if frames_data else {}
    return {
        "frames_processed": len(frames_data),
        "final_score": last.get("score", 0),
        "final_alert_level": last.get("alert_level", 0),
        "total_blinks": last.get("blink_count", 0),
        "frames": frames_data,
    }


@app.post("/analyze-stream")
async def analyze_stream(file: UploadFile = File(...)):
    """Stream NDJSON analysis results frame by frame as the video is processed."""
    suffix = Path(file.filename).suffix if file.filename else ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def worker():
        try:
            cap = cv2.VideoCapture(tmp_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            tracker = EyeTrackerCore(_model_path)
            frames_data = []
            frame_num = 0

            asyncio.run_coroutine_threadsafe(
                queue.put(json.dumps({"type": "meta", "total_frames": total, "fps": fps}) + "\n"),
                loop,
            ).result()

            while cap.isOpened():
                ok, frame = cap.read()
                if not ok:
                    break
                timestamp_ms = int(frame_num * (1000.0 / fps))
                state = tracker.process_frame(frame, timestamp_ms)
                d = asdict(state)
                d["type"] = "frame"
                d["frame_index"] = frame_num
                frames_data.append(d)

                if frame_num % 5 == 0:  # send every 5th frame to keep stream manageable
                    asyncio.run_coroutine_threadsafe(
                        queue.put(json.dumps(d) + "\n"), loop
                    ).result()

                frame_num += 1

            cap.release()

            last = frames_data[-1] if frames_data else {}
            asyncio.run_coroutine_threadsafe(
                queue.put(
                    json.dumps({
                        "type": "summary",
                        "frames_processed": len(frames_data),
                        "final_score": last.get("score", 0),
                        "final_alert_level": last.get("alert_level", 0),
                        "total_blinks": last.get("blink_count", 0),
                    }) + "\n"
                ),
                loop,
            ).result()

        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                queue.put(json.dumps({"type": "error", "message": str(e)}) + "\n"), loop
            ).result()
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    async def generate():
        _executor.submit(worker)
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return StreamingResponse(generate(), media_type="text/plain")


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
