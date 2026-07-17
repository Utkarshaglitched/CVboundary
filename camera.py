from __future__ import annotations

import threading
import time
from typing import Optional

import cv2
import numpy as np


class CameraManager:
    _instance: Optional["CameraManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "CameraManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_error: Optional[str] = None

    def start(self) -> bool:
        if self._running:
            return True
        self._cap = cv2.VideoCapture(0)
        if not self._cap.isOpened():
            self._last_error = "Camera Offline"
            return False
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, name="camera-capture", daemon=True)
        self._thread.start()
        return True

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._cap is None:
                break
            ret, frame = self._cap.read()
            if not ret or frame is None:
                self._last_error = "Camera Offline"
                time.sleep(0.2)
                continue
            with self._lock:
                self._frame = frame.copy()
            self._last_error = None
            time.sleep(0.01)

    def read_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
        self._cap = None
        self._frame = None

    @property
    def is_running(self) -> bool:
        return self._running and not self._stop_event.is_set()

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error
