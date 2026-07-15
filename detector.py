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
    BOUNDARY_PERCENTAGE,
    CAPTURED_IMAGES_DIR,
    CONFIDENCE_THRESHOLD,
    FACE_SIMILARITY_THRESHOLD,
    INTRUSION_LOG_INTERVAL_SECONDS,
    YOLO_MODEL_PATH,
)
from face_recognition import FaceRecognizer


class IntrusionDetector:
    def __init__(self, face_recognizer: FaceRecognizer, on_intrusion: Optional[Callable[[str, str], None]] = None) -> None:
        self.model = YOLO(YOLO_MODEL_PATH)
        self.face_recognizer = face_recognizer
        self.camera = CameraManager()
        self.on_intrusion = on_intrusion
        self.last_intrusion_time = 0.0
        self._running = False
        self._capture_thread: Optional[threading.Thread] = None
        self._analysis_thread: Optional[threading.Thread] = None
        self._raw_frame: Optional[np.ndarray] = None
        self._processed_frame: Optional[np.ndarray] = None
        self._raw_lock = threading.Lock()
        self._processed_lock = threading.Lock()
        self._last_intrusion_signature: Optional[tuple] = None
        self.status = "SAFE"
        self.last_recognized_people: list[str] = []

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._analysis_thread = threading.Thread(target=self._analysis_loop, daemon=True)
        self._capture_thread.start()
        self._analysis_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=1.0)
        if self._analysis_thread is not None:
            self._analysis_thread.join(timeout=1.0)

    def get_processed_frame(self) -> Optional[np.ndarray]:
        with self._processed_lock:
            if self._processed_frame is None:
                return None
            return self._processed_frame.copy()

    def get_detection_overlays(self) -> list[dict[str, object]]:
        with self._processed_lock:
            if self._processed_frame is None:
                return []
            return getattr(self, "_last_detections", [])

    def _capture_loop(self) -> None:
        while self._running:
            frame = self.camera.read_frame()
            if frame is None:
                self.status = "CAMERA OFFLINE"
                time.sleep(0.1)
                continue
            with self._raw_lock:
                self._raw_frame = frame
            time.sleep(0.01)

    def _analysis_loop(self) -> None:
        while self._running:
            frame = None
            with self._raw_lock:
                if self._raw_frame is not None:
                    frame = self._raw_frame.copy()
            if frame is None:
                time.sleep(0.05)
                continue
            self._process_frame(frame)
            time.sleep(ANALYSIS_INTERVAL_SECONDS)

    def _process_frame(self, frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        boundary_x = int(width * BOUNDARY_PERCENTAGE)

        cv2.line(frame, (boundary_x, 0), (boundary_x, height), (0, 0, 255), 3)
        cv2.putText(frame, "DANGER ZONE", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.putText(frame, "SAFE ZONE", (boundary_x + 10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

        results = self.model(frame, verbose=False)
        intrusion_detected = False
        recognized_people: list[str] = []
        danger_detections: list[tuple[str, str]] = []

        detections = []
        for result in results:
            for box in result.boxes:
                if int(box.cls[0]) != 0:
                    continue
                conf = float(box.conf[0])
                if conf < CONFIDENCE_THRESHOLD:
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0])
                if x1 < 0:
                    x1 = 0
                if y1 < 0:
                    y1 = 0
                if x2 > width:
                    x2 = width
                if y2 > height:
                    y2 = height

                is_danger = (x1 + x2) // 2 < boundary_x
                status_text = "DANGER" if is_danger else "SAFE"

                person_roi = frame[y1:y2, x1:x2]
                recognized = self.face_recognizer.recognize(person_roi)
                recognized_name = recognized[0] if recognized else "Unknown"

                detections.append({
                    "box": (x1, y1, x2, y2),
                    "name": recognized_name,
                    "danger": is_danger,
                    "confidence": conf,
                })

                if is_danger:
                    intrusion_detected = True
                    recognized_people.append(recognized_name)
                    danger_detections.append((recognized_name, status_text))

        if intrusion_detected:
            self.status = "INTRUSION"
            current_signature = tuple(sorted(danger_detections))
            now = time.time()
            should_log = False
            if self._last_intrusion_signature is None:
                should_log = True
            elif current_signature != self._last_intrusion_signature:
                should_log = True
            elif now - self.last_intrusion_time >= INTRUSION_LOG_INTERVAL_SECONDS:
                should_log = True

            if should_log:
                self._last_intrusion_signature = current_signature
                self.last_intrusion_time = now
                self._handle_intrusion(frame, recognized_people)

            cv2.rectangle(frame, (0, 0), (width, 70), (0, 0, 255), -1)
            cv2.putText(frame, "INTRUSION DETECTED", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
        else:
            self.status = "SAFE"
            self._last_intrusion_signature = None
            cv2.rectangle(frame, (0, 0), (width, 70), (0, 150, 0), -1)
            cv2.putText(frame, "AREA SAFE", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)

        self._last_detections = detections
        with self._processed_lock:
            self._processed_frame = frame.copy()
        self.last_recognized_people = recognized_people

    def _handle_intrusion(self, frame: np.ndarray, recognized_people: list[str]) -> None:
        if not CAPTURED_IMAGES_DIR.exists():
            CAPTURED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = CAPTURED_IMAGES_DIR / f"{timestamp}.jpg"
        success = cv2.imwrite(str(image_path), frame)
        if not success:
            return

        recognized_list = [name for name in recognized_people if name]
        if not recognized_list:
            recognized_list = ["Unknown"]
        names = ", ".join(recognized_list)

        def worker() -> None:
            if self.on_intrusion is not None:
                self.on_intrusion(str(image_path), names)

        threading.Thread(target=worker, daemon=True).start()
