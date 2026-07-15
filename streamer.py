from __future__ import annotations

import threading
import time
from typing import Any, Callable, List, Optional

import cv2
import numpy as np
from fastapi.responses import StreamingResponse

from camera import CameraManager
from config import BOUNDARY_PERCENTAGE


class Streamer:
    def __init__(self) -> None:
        self.camera = CameraManager()
        self._stop_event = threading.Event()
        self._overlay_supplier: Optional[Callable[[], List[dict[str, Any]]]] = None

    def set_overlay_supplier(self, supplier: Callable[[], List[dict[str, Any]]]) -> None:
        self._overlay_supplier = supplier

    def _draw_overlays(self, frame: np.ndarray, detections: List[dict[str, Any]]) -> None:
        height, width = frame.shape[:2]
        boundary_x = int(width * BOUNDARY_PERCENTAGE)
        cv2.line(frame, (boundary_x, 0), (boundary_x, height), (0, 0, 255), 3)
        cv2.putText(frame, "DANGER ZONE", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.putText(frame, "SAFE ZONE", (boundary_x + 10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

        for det in detections:
            x1, y1, x2, y2 = det["box"]
            name = det.get("name", "Unknown")
            is_danger = det.get("danger", False)
            status_color = (0, 0, 255) if is_danger else (0, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), status_color, 2)
            cv2.putText(frame, f"{name}", (x1, max(y1 - 10, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, "DANGER" if is_danger else "SAFE", (x1, y2 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)

    def _downscale_frame(self, frame: np.ndarray) -> np.ndarray:
        max_width = 640
        height, width = frame.shape[:2]
        if width > max_width:
            scale = max_width / float(width)
            new_size = (max_width, int(height * scale))
            return cv2.resize(frame, new_size, interpolation=cv2.INTER_LINEAR)
        return frame

    def generate_mjpeg(self):
        while not self._stop_event.is_set():
            frame = self.camera.read_frame()
            if frame is None:
                time.sleep(0.02)
                continue

            if self._overlay_supplier is not None:
                detections = self._overlay_supplier()
                if detections:
                    self._draw_overlays(frame, detections)

            frame = self._downscale_frame(frame)
            _, encoded = cv2.imencode(".jpg", frame)
            frame_bytes = encoded.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n\r\n" + frame_bytes + b"\r\n"
            )
            time.sleep(0.03)

    def start(self) -> None:
        self._stop_event.clear()

    def stop(self) -> None:
        self._stop_event.set()

    def response(self) -> StreamingResponse:
        return StreamingResponse(
            self.generate_mjpeg(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )
