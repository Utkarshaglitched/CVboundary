from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
from ultralytics import YOLO

from camera import CameraManager
from config import (
    ANALYSIS_INTERVAL_SECONDS,
    CAPTURED_IMAGES_DIR,
    CONFIDENCE_THRESHOLD,
    INTRUSION_EMBEDDINGS_DIR,
    YOLO_MODEL_PATH,
)
from face_recognition import FaceRecognizer
from perimeter import PerimeterManager


class PersonTrack:
    """Simple state holder for a temporary person track used to confirm intrusions."""

    def __init__(self, track_id: int, box: tuple[int, int, int, int], foot_point: tuple[int, int], seen_at: float) -> None:
        self.track_id = track_id
        self.current_box = box
        self.current_foot_point = foot_point
        self.first_seen_time: Optional[float] = None
        self.last_seen_time = seen_at
        self.inside_danger_zone = False
        self.confirmed_intrusion = False
        self.capture_done = False

    def update(self, box: tuple[int, int, int, int], foot_point: tuple[int, int], now: float, inside_danger_zone: bool) -> bool:
        """Return True once the track has stayed in the danger zone for at least 1 second."""
        self.current_box = box
        self.current_foot_point = foot_point
        self.last_seen_time = now
        self.inside_danger_zone = inside_danger_zone

        if not inside_danger_zone:
            self.first_seen_time = None
            self.confirmed_intrusion = False
            self.capture_done = False
            return False

        if self.first_seen_time is None:
            self.first_seen_time = now
            return False

        if not self.confirmed_intrusion and (now - self.first_seen_time) >= 1.0:
            self.confirmed_intrusion = True
            return True

        return False


def _crop_person(frame: np.ndarray, box: tuple[int, int, int, int]) -> Optional[np.ndarray]:
    x1, y1, x2, y2 = box
    height, width = frame.shape[:2]
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(width, x2)
    y2 = min(height, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return None
    return roi.copy()


class IntrusionDetector:
    def __init__(
        self,
        face_recognizer: FaceRecognizer,
        perimeter_manager: PerimeterManager,
        on_intrusion: Optional[Callable[[str, Optional[str]], None]] = None,
        on_status_change: Optional[Callable[[int], None]] = None,
    ) -> None:
        self.model = YOLO(YOLO_MODEL_PATH)
        self.face_recognizer = face_recognizer
        self.perimeter = perimeter_manager
        self.camera = CameraManager()
        self.on_intrusion = on_intrusion
        self.on_status_change = on_status_change
        self._running = False
        self._stop_event = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._analysis_thread: Optional[threading.Thread] = None
        self._raw_frame: Optional[np.ndarray] = None
        self._processed_frame: Optional[np.ndarray] = None
        self._raw_lock = threading.Lock()
        self._processed_lock = threading.Lock()
        self.status = "SAFE"
        self._person_tracks: dict[int, PersonTrack] = {}
        self._next_track_id = 1
        self._track_match_threshold = 150

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._capture_thread = threading.Thread(target=self._capture_loop, name="detector-capture", daemon=True)
        self._analysis_thread = threading.Thread(target=self._analysis_loop, name="detector-analysis", daemon=True)
        self._capture_thread.start()
        self._analysis_thread.start()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=1.0)
            self._capture_thread = None
        if self._analysis_thread is not None:
            self._analysis_thread.join(timeout=1.0)
            self._analysis_thread = None
        self.camera.stop()

    def get_current_frame(self) -> Optional[np.ndarray]:
        with self._raw_lock:
            if self._raw_frame is None:
                return None
            return cv2.flip(self._raw_frame.copy(), 1)

    def get_detection_overlays(self) -> list[dict[str, object]]:
        with self._processed_lock:
            if self._processed_frame is None:
                return []
            return getattr(self, "_last_detections", [])

    def get_perimeter_points(self) -> list[tuple[int, int]]:
        with self._processed_lock:
            if self._processed_frame is None:
                return []
            height, width = self._processed_frame.shape[:2]
            return self.perimeter.get_pixel_points(width, height)

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            frame = self.camera.read_frame()
            if frame is None:
                self.status = "CAMERA OFFLINE"
                time.sleep(0.1)
                continue
            with self._raw_lock:
                self._raw_frame = frame
            time.sleep(0.01)

    def _analysis_loop(self) -> None:
        while not self._stop_event.is_set():
            frame = None
            with self._raw_lock:
                if self._raw_frame is not None:
                    frame = self._raw_frame.copy()
            if frame is None:
                time.sleep(0.05)
                continue
            self._process_frame(frame)
            time.sleep(ANALYSIS_INTERVAL_SECONDS)

    def _capture_intruder(self, person_roi: np.ndarray) -> None:
        def worker() -> None:
            if not CAPTURED_IMAGES_DIR.exists():
                CAPTURED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            image_path = CAPTURED_IMAGES_DIR / f"person_{timestamp}.jpg"
            if not cv2.imwrite(str(image_path), person_roi):
                return

            embeddings_path: Optional[Path] = None
            embeddings = self.face_recognizer.extract_embeddings(person_roi)
            if embeddings:
                INTRUSION_EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
                embeddings_path = INTRUSION_EMBEDDINGS_DIR / f"person_{timestamp}.npy"
                if len(embeddings) == 1:
                    np.save(str(embeddings_path), embeddings[0])
                else:
                    np.save(str(embeddings_path), np.stack(embeddings))

            if self.on_intrusion is not None:
                self.on_intrusion(str(image_path), str(embeddings_path) if embeddings_path else None)

        threading.Thread(target=worker, name="intrusion-worker", daemon=True).start()

    def _draw_perimeter(self, frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        points = self.perimeter.get_pixel_points(width, height)
        if len(points) >= 2:
            for index in range(len(points) - 1):
                cv2.line(frame, points[index], points[index + 1], (0, 0, 255), 3)
        cv2.putText(frame, "DANGER ZONE", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        if points:
            safe_x = min(width - 120, points[-1][0] + 10)
            cv2.putText(frame, "SAFE ZONE", (safe_x, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

    def _process_frame(self, frame: np.ndarray) -> None:
        frame = cv2.flip(frame, 1)
        height, width = frame.shape[:2]

        self._draw_perimeter(frame)

        results = self.model(frame, verbose=False)
        detections: list[dict[str, object]] = []
        for result in results:
            for box in result.boxes:
                if int(box.cls[0]) != 0:
                    continue
                conf = float(box.conf[0])
                if conf < CONFIDENCE_THRESHOLD:
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0])
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(width, x2)
                y2 = min(height, y2)

                foot_x = (x1 + x2) // 2
                foot_y = y2
                is_danger = self.perimeter.is_danger(foot_x, foot_y, width, height)
                detections.append({
                    "box": (x1, y1, x2, y2),
                    "danger": is_danger,
                    "confidence": conf,
                    "foot_point": (foot_x, foot_y),
                })

        now = time.time()
        matched_indices: set[int] = set()
        next_tracks: dict[int, PersonTrack] = {}

        for track in self._person_tracks.values():
            best_idx: Optional[int] = None
            best_distance: Optional[float] = None
            for idx, detection in enumerate(detections):
                if idx in matched_indices:
                    continue
                foot_point = detection["foot_point"]
                assert isinstance(foot_point, tuple)
                distance = abs(track.current_foot_point[0] - foot_point[0]) + abs(track.current_foot_point[1] - foot_point[1])
                if best_distance is None or distance < best_distance:
                    best_distance = float(distance)
                    best_idx = idx
            if best_idx is None or best_distance is None or best_distance > self._track_match_threshold:
                continue

            matched_indices.add(best_idx)
            detection = detections[best_idx]
            box = detection["box"]
            foot_point = detection["foot_point"]
            assert isinstance(box, tuple)
            assert isinstance(foot_point, tuple)
            inside_danger_zone = bool(detection["danger"])
            confirmed_now = track.update(box, foot_point, now, inside_danger_zone)
            if track.inside_danger_zone:
                next_tracks[track.track_id] = track
            if confirmed_now and not track.capture_done:
                track.capture_done = True
                person_roi = _crop_person(frame, box)
                if person_roi is not None:
                    self._capture_intruder(person_roi)

        for idx, detection in enumerate(detections):
            if idx in matched_indices:
                continue
            box = detection["box"]
            foot_point = detection["foot_point"]
            assert isinstance(box, tuple)
            assert isinstance(foot_point, tuple)
            track = PersonTrack(self._next_track_id, box, foot_point, now)
            self._next_track_id += 1
            track.update(box, foot_point, now, bool(detection["danger"]))
            next_tracks[track.track_id] = track
            if track.inside_danger_zone:
                track.first_seen_time = now

        self._person_tracks = next_tracks

        intrusion_detected = any(track.confirmed_intrusion for track in self._person_tracks.values())

        if intrusion_detected:
            if self.status != "INTRUSION":
                self.status = "INTRUSION"
                if self.on_status_change is not None:
                    self.on_status_change(1)
            cv2.rectangle(frame, (0, 0), (width, 70), (0, 0, 255), -1)
            cv2.putText(frame, "INTRUSION DETECTED", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
        else:
            if self.status == "INTRUSION":
                if self.on_status_change is not None:
                    self.on_status_change(0)
            self.status = "SAFE"
            cv2.rectangle(frame, (0, 0), (width, 70), (0, 150, 0), -1)
            cv2.putText(frame, "AREA SAFE", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)

        self._last_detections = detections
        with self._processed_lock:
            self._processed_frame = frame.copy()
