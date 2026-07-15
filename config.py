from pathlib import Path
from typing import Final

BASE_DIR: Final[Path] = Path(__file__).resolve().parent

YOLO_MODEL_PATH: Final[str] = str(BASE_DIR / "MODELS" / "yolo11x.pt")
CONFIDENCE_THRESHOLD: Final[float] = 0.5
ANALYSIS_INTERVAL_SECONDS: Final[float] = 0.1
INTRUSION_LOG_INTERVAL_SECONDS: Final[int] = 30
BOUNDARY_PERCENTAGE: Final[float] = 0.25
FACE_SIMILARITY_THRESHOLD: Final[float] = 0.55
DATABASE_PATH: Final[str] = str(BASE_DIR / "database" / "database.db")
KNOWN_FACES_DIR: Final[Path] = BASE_DIR / "known_faces"
EMBEDDINGS_DIR: Final[Path] = BASE_DIR / "numpy-saves"
CAPTURED_IMAGES_DIR: Final[Path] = BASE_DIR / "captured_intrusions"
