from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Union

import cv2
import numpy as np

try:
    from insightface.app import FaceAnalysis
except Exception:  # pragma: no cover - fallback for environments without InsightFace assets
    FaceAnalysis = None

from config import EMBEDDINGS_DIR, FACE_SIMILARITY_THRESHOLD, KNOWN_FACES_DIR
from cosine import cosine_similarity


class FaceRecognizer:
    def __init__(self) -> None:
        self.app = None
        self.known_embeddings: Dict[str, List[np.ndarray]] = {}
        if FaceAnalysis is not None:
            try:
                self.app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
                self.app.prepare(ctx_id=0, det_size=(640, 640))
            except Exception:
                self.app = None
        self._load_known_embeddings()

    def _load_known_embeddings(self) -> None:
        self.known_embeddings = {}
        if EMBEDDINGS_DIR.exists():
            for embedding_path in sorted(EMBEDDINGS_DIR.glob("*.npy")):
                try:
                    data = np.load(str(embedding_path), allow_pickle=False)
                except Exception:
                    continue
                if data.ndim == 1:
                    embeddings = [data]
                elif data.ndim == 2:
                    embeddings = [row for row in data]
                else:
                    embeddings = [data.ravel()]
                person_name = embedding_path.stem.replace("-", " ").replace("_", " ").title()
                self.known_embeddings.setdefault(person_name, []).extend(embeddings)

        if KNOWN_FACES_DIR.exists():
            for person_dir in sorted(KNOWN_FACES_DIR.iterdir()):
                if not person_dir.is_dir():
                    continue
                embeddings: List[np.ndarray] = []
                for image_path in sorted(person_dir.glob("*")):
                    if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                        continue
                    image = cv2.imread(str(image_path))
                    if image is None or self.app is None:
                        continue
                    faces = self.app.get(image)
                    if faces:
                        embeddings.append(faces[0].embedding)
                if embeddings:
                    self.known_embeddings.setdefault(person_dir.name.title(), []).extend(embeddings)

    def _embed_image(self, image: np.ndarray) -> List[np.ndarray]:
        if self.app is None:
            return []
        try:
            faces = self.app.get(image)
        except Exception:
            return []
        if not faces:
            return []
        return [face.embedding for face in faces]

    def _recognize_embedding(self, embedding: np.ndarray) -> str:
        best_score = 0.0
        best_name = "Unknown"
        for name, stored_embeddings in self.known_embeddings.items():
            for stored_embedding in stored_embeddings:
                similarity = cosine_similarity(embedding, stored_embedding)
                if similarity > best_score:
                    best_score = similarity
                    best_name = name
        if best_score >= FACE_SIMILARITY_THRESHOLD:
            return best_name
        return "Unknown"

    def extract_embeddings(self, image: Union[str, np.ndarray]) -> List[np.ndarray]:
        if isinstance(image, str):
            image = cv2.imread(image)
        if image is None:
            return []
        return self._embed_image(image)

    def identify_embedding(self, embedding: np.ndarray) -> str:
        return self._recognize_embedding(embedding)

    def identify_from_path(self, embeddings_path: str) -> str:
        path = Path(embeddings_path)
        if not path.exists():
            return "Unknown"
        try:
            data = np.load(str(path), allow_pickle=False)
        except Exception:
            return "Unknown"
        if data.ndim == 1:
            embeddings = [data]
        elif data.ndim == 2:
            embeddings = [row for row in data]
        else:
            embeddings = [data.ravel()]
        names = [self.identify_embedding(embedding) for embedding in embeddings]
        unique_names = []
        for name in names:
            if name not in unique_names:
                unique_names.append(name)
        return ", ".join(unique_names) if unique_names else "Unknown"

    def recognize(self, image: Union[str, np.ndarray]) -> List[str]:
        if isinstance(image, str):
            image = cv2.imread(image)
        if image is None:
            return ["Unknown"]
        embeddings = self._embed_image(image)
        if not embeddings:
            return ["Unknown"]
        return [self._recognize_embedding(embedding) for embedding in embeddings]
