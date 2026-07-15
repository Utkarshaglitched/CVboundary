from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import List, Tuple

Point = Tuple[float, float]


class PerimeterManager:
    """Stores a user-drawn boundary line as normalized (0-1) polyline points."""

    def __init__(self, path: Path, default_x: float = 0.25, default_danger_side: str = "left") -> None:
        self.path = path
        self.default_x = default_x
        self._points: List[Point] = []
        self._danger_side = default_danger_side
        self._lock = Lock()
        self.load()

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._points = []
                self._danger_side = "left"
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._points = []
                self._danger_side = "left"
                return
            self._points = [(float(p["x"]), float(p["y"])) for p in data.get("points", [])]
            raw_danger_side = data.get("danger_side", "left")
            self._danger_side = raw_danger_side if raw_danger_side in {"left", "right"} else "left"

    def save(self, points: List[Point], danger_side: str | None = None) -> None:
        with self._lock:
            self._points = list(points)
            if danger_side in {"left", "right"}:
                self._danger_side = danger_side
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "points": [{"x": x, "y": y} for x, y in self._points],
                "danger_side": self._danger_side,
            }
            self.path.write_text(json.dumps(payload), encoding="utf-8")

    def clear(self) -> None:
        with self._lock:
            self._points = []
            if self.path.exists():
                self.path.unlink(missing_ok=True)

    def get_points(self) -> List[Point]:
        with self._lock:
            return list(self._points)

    def get_danger_side(self) -> str:
        with self._lock:
            return self._danger_side

    def get_pixel_points(self, width: int, height: int) -> List[Tuple[int, int]]:
        points = self.get_points()
        if not points:
            boundary_x = int(width * self.default_x)
            return [(boundary_x, 0), (boundary_x, height - 1)]
        return [(int(x * width), int(y * height)) for x, y in points]

    def is_danger(self, foot_x: int, foot_y: int, width: int, height: int) -> bool:
        boundary_x = self._boundary_x_at_y(self.get_pixel_points(width, height), foot_y)
        if self.get_danger_side() == "right":
            return foot_x > boundary_x
        return foot_x < boundary_x

    @staticmethod
    def _boundary_x_at_y(points: List[Tuple[int, int]], y: int) -> int:
        if not points:
            return 0
        if len(points) == 1:
            return points[0][0]

        sorted_points = sorted(points, key=lambda point: point[1])
        if y <= sorted_points[0][1]:
            return sorted_points[0][0]
        if y >= sorted_points[-1][1]:
            return sorted_points[-1][0]

        for index in range(len(sorted_points) - 1):
            x1, y1 = sorted_points[index]
            x2, y2 = sorted_points[index + 1]
            if y1 <= y <= y2:
                if y2 == y1:
                    return (x1 + x2) // 2
                ratio = (y - y1) / (y2 - y1)
                return int(x1 + ratio * (x2 - x1))
        return sorted_points[-1][0]
