import os
import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
MODEL_FILENAME = "face_landmarker.task"


def ensure_model(models_dir: str = None) -> str:
    if models_dir is None:
        models_dir = Path(__file__).parent.parent / "models"
    models_dir = Path(models_dir)
    models_dir.mkdir(exist_ok=True)

    model_path = models_dir / MODEL_FILENAME
    if not model_path.exists():
        print(f"Downloading MediaPipe face landmarker model (~32 MB)...")
        print(f"  -> {model_path}")

        def _progress(count, block_size, total):
            if total > 0:
                pct = min(100, count * block_size * 100 // total)
                print(f"\r  {pct}%", end="", flush=True)

        urllib.request.urlretrieve(MODEL_URL, str(model_path), reporthook=_progress)
        print()
        print("  Model ready.")

    return str(model_path)
