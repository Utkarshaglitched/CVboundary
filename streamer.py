from __future__ import annotations

import threading
import time
from typing import Any, Callable, List, Optional

import cv2
import numpy as np
from fastapi.responses import StreamingResponse

from camera import CameraManager
from perimeter import PerimeterManager


class Streamer:
    def __init__(self, perimeter_manager: PerimeterManager) -> None:
        self.camera = CameraManager()
        self.perimeter = perimeter_manager
        self._stop_event = threading.Event()
        self._overlay_supplier: Optional[Callable[[], List[dict[str, Any]]]] = None
        self._perimeter_supplier: Optional[Callable[[], List[tuple[int, int]]]] = None

    def set_overlay_supplier(self, supplier: Callable[[], List[dict[str, Any]]]) -> None:
        self._overlay_supplier = supplier

    def set_perimeter_supplier(self, supplier: Callable[[], List[tuple[int, int]]]) -> None:
        self._perimeter_supplier = supplier

    def _draw_perimeter(self, frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        points: list[tuple[int, int]] = []
        if self._perimeter_supplier is not None:
            points = self._perimeter_supplier()
        if not points:
            points = self.perimeter.get_pixel_points(width, height)

        if len(points) >= 2:
            for index in range(len(points) - 1):
                cv2.line(frame, points[index], points[index + 1], (0, 0, 255), 3)

    def _draw_overlays(self, frame: np.ndarray, detections: List[dict[str, Any]]) -> None:
        self._draw_perimeter(frame)

        for det in detections:
            x1, y1, x2, y2 = det["box"]
            is_danger = det.get("danger", False)
            status_color = (0, 0, 255) if is_danger else (0, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), status_color, 2)

    def generate_mjpeg(self):
        while not self._stop_event.is_set():
            frame = self.camera.read_frame()
            if frame is None:
                time.sleep(0.02)
                continue

            frame = cv2.flip(frame, 1)

            if self._overlay_supplier is not None:
                detections = self._overlay_supplier()
                if detections:
                    self._draw_overlays(frame, detections)
                else:
                    self._draw_perimeter(frame)
            else:
                self._draw_perimeter(frame)

            _, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
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
