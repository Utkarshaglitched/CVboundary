from __future__ import annotations

import json
import os
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import crud
import database
from camera import CameraManager
from detector import IntrusionDetector
from face_recognition import FaceRecognizer
from models import IntrusionLog
from perimeter import PerimeterManager
from streamer import Streamer

app = FastAPI(title="Surveillance Dashboard", version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

latest_intrusion_status = {"value": 0, "updated_at": None}
perimeter_manager = PerimeterManager(config.PERIMETER_FILE, default_x=config.BOUNDARY_PERCENTAGE)


def _normalize_intrusion_value(payload: object) -> int:
    if isinstance(payload, dict):
        for key in ("value", "status", "intrusion", "alarm"):
            if key not in payload:
                continue
            value = payload[key]
            if isinstance(value, bool):
                return 1 if value else 0
            if isinstance(value, (int, float)):
                return 1 if int(value) != 0 else 0
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"1", "true", "on", "high", "intrusion"}:
                    return 1
                if normalized in {"0", "false", "off", "low", "safe"}:
                    return 0
    if isinstance(payload, bool):
        return 1 if payload else 0
    if isinstance(payload, (int, float)):
        return 1 if int(payload) != 0 else 0
    if isinstance(payload, str):
        normalized = payload.strip().lower()
        if normalized in {"1", "true", "on", "high", "intrusion"}:
            return 1
        if normalized in {"0", "false", "off", "low", "safe"}:
            return 0
    return 0


def _notify_alarm_board(value: int) -> None:
    alarm_url = os.getenv("ALARM_WEBHOOK_URL")
    if not alarm_url:
        return
    try:
        payload = json.dumps({"value": value}).encode("utf-8")
        request = urllib.request.Request(
            alarm_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            response.read()
    except Exception:
        return


camera = CameraManager()
streamer = Streamer(perimeter_manager)
face_recognizer = FaceRecognizer()


def handle_intrusion(image_path: str, embeddings_path: str | None) -> None:
    db = database.SessionLocal()
    try:
        crud.create_log(
            db,
            image_path=image_path,
            embeddings_path=embeddings_path,
            recognized_people="Pending",
        )
    finally:
        db.close()
    _notify_alarm_board(1)


def update_intrusion_status(value: int) -> None:
    latest_intrusion_status["value"] = value
    latest_intrusion_status["updated_at"] = datetime.utcnow().isoformat()


def _persist_log_identity(log_id: int, recognized_people: str) -> None:
    db = database.SessionLocal()
    try:
        entry = db.query(IntrusionLog).filter(IntrusionLog.id == log_id).first()
        if entry is not None and entry.recognized_people in {"Pending", "Unknown"}:
            entry.recognized_people = recognized_people
            db.commit()
    finally:
        db.close()


def resolve_log_identity(entry: IntrusionLog | None) -> str:
    if entry is None:
        return "Unknown"

    if entry.recognized_people and entry.recognized_people not in {"Pending", "Unknown"}:
        return entry.recognized_people

    if entry.embeddings_path:
        recognized_people = face_recognizer.identify_from_path(entry.embeddings_path)
        if recognized_people not in {"Pending", "Unknown"}:
            _persist_log_identity(entry.id, recognized_people)
        return recognized_people

    return "Unknown"


detector = IntrusionDetector(
    face_recognizer=face_recognizer,
    perimeter_manager=perimeter_manager,
    on_intrusion=handle_intrusion,
    on_status_change=update_intrusion_status,
)
streamer.set_overlay_supplier(detector.get_detection_overlays)
streamer.set_perimeter_supplier(detector.get_perimeter_points)


@app.on_event("startup")
def startup_event() -> None:
    database.init_db()
    os.makedirs(config.CAPTURED_IMAGES_DIR, exist_ok=True)
    os.makedirs(config.INTRUSION_EMBEDDINGS_DIR, exist_ok=True)
    os.makedirs(config.KNOWN_FACES_DIR, exist_ok=True)
    camera.start()
    streamer.start()
    detector.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    detector.stop()
    streamer.stop()
    camera.stop()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    db = database.SessionLocal()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        count = db.query(IntrusionLog).filter(IntrusionLog.timestamp.like(f"{today}%")).count()
        latest = db.query(IntrusionLog).order_by(IntrusionLog.id.desc()).first()
        latest_person = resolve_log_identity(latest) if latest else "None"
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "camera_status": "Online" if camera.is_running else "Offline",
                "intrusions_today": count,
                "latest_person": latest_person,
                "system_status": detector.status,
            },
        )
    finally:
        db.close()


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "settings.html", {"request": request})


@app.get("/video_feed")
async def video_feed() -> StreamingResponse:
    return streamer.response()


@app.get("/api/settings/frame")
async def settings_frame() -> Response:
    frame = detector.get_current_frame()
    if frame is None:
        frame = camera.read_frame()
        if frame is not None:
            frame = cv2.flip(frame, 1)
    if frame is None:
        raise HTTPException(status_code=503, detail="Camera unavailable")
    success, encoded = cv2.imencode(".jpg", frame)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to encode frame")
    return Response(content=encoded.tobytes(), media_type="image/jpeg")


@app.get("/api/perimeter")
async def get_perimeter() -> JSONResponse:
    return JSONResponse({
        "points": [{"x": x, "y": y} for x, y in perimeter_manager.get_points()],
        "danger_side": perimeter_manager.get_danger_side(),
    })


@app.post("/api/perimeter")
async def save_perimeter(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    raw_points = body.get("points", [])
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        raise HTTPException(status_code=400, detail="Draw at least two points for the perimeter line")

    points: list[tuple[float, float]] = []
    for point in raw_points:
        if not isinstance(point, dict) or "x" not in point or "y" not in point:
            continue
        x = float(point["x"])
        y = float(point["y"])
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            points.append((x, y))

    if len(points) < 2:
        raise HTTPException(status_code=400, detail="At least two valid points are required")

    danger_side = body.get("danger_side", perimeter_manager.get_danger_side())
    if danger_side not in {"left", "right"}:
        raise HTTPException(status_code=400, detail="Invalid danger side")

    perimeter_manager.save(points, danger_side=danger_side)
    return JSONResponse({
        "ok": True,
        "points": [{"x": x, "y": y} for x, y in points],
        "danger_side": danger_side,
    })


@app.delete("/api/perimeter")
async def clear_perimeter() -> JSONResponse:
    perimeter_manager.clear()
    return JSONResponse({"ok": True})


@app.get("/captures/{image_name}")
async def captured_image(image_name: str) -> FileResponse:
    safe_name = Path(image_name).name
    image_path = config.CAPTURED_IMAGES_DIR / safe_name
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(image_path, media_type="image/jpeg")


@app.post("/intrusion/status")
async def intrusion_status(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}

    value = _normalize_intrusion_value(body)
    latest_intrusion_status["value"] = value
    latest_intrusion_status["updated_at"] = datetime.utcnow().isoformat()
    return JSONResponse({"ok": True, "value": value, "message": "Intrusion status updated"})


@app.get("/intrusion/status")
async def get_intrusion_status() -> JSONResponse:
    return JSONResponse({
        "value": latest_intrusion_status["value"],
        "updated_at": latest_intrusion_status["updated_at"],
    })


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "logs.html", {"request": request})


@app.get("/api/logs")
async def api_logs(query: str | None = None, filter: str | None = None, sort: str | None = None) -> JSONResponse:
    db = database.SessionLocal()
    try:
        sort_newest = sort != "oldest"
        items = crud.list_logs(db, query=query, filter_kind=None, sort_newest=sort_newest)

        payload = []
        for entry in items:
            recognized_people = resolve_log_identity(entry)
            payload.append({
                "id": entry.id,
                "timestamp": entry.timestamp,
                "image_url": f"/captures/{Path(entry.image_path).name}",
                "recognized_people": recognized_people,
                "person_count": len([name for name in recognized_people.split(",") if name.strip()]),
                "status": entry.status,
            })

        if query:
            q = query.lower()
            payload = [
                item for item in payload
                if q in item["recognized_people"].lower()
                or q in item["timestamp"].lower()
                or q in item["status"].lower()
            ]

        if filter == "known":
            payload = [item for item in payload if "unknown" not in item["recognized_people"].lower()]
        elif filter == "unknown":
            payload = [item for item in payload if "unknown" in item["recognized_people"].lower()]
        elif filter == "multiple":
            payload = [item for item in payload if item["person_count"] > 1]

        return JSONResponse(payload)
    finally:
        db.close()


@app.get("/api/log/{log_id}")
async def get_log(log_id: int) -> JSONResponse:
    db = database.SessionLocal()
    try:
        entry = crud.get_log(db, log_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Log not found")
        return JSONResponse({
            "id": entry.id,
            "timestamp": entry.timestamp,
            "image_path": entry.image_path,
            "recognized_people": resolve_log_identity(entry),
            "status": entry.status,
        })
    finally:
        db.close()


@app.delete("/api/log/{log_id}")
async def delete_log(log_id: int) -> JSONResponse:
    db = database.SessionLocal()
    try:
        removed = crud.delete_log(db, log_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Log not found")
        return JSONResponse({"success": True, "message": "Log deleted"})
    finally:
        db.close()


@app.delete("/api/logs")
async def delete_all_logs() -> JSONResponse:
    db = database.SessionLocal()
    try:
        count = crud.delete_all_logs(db)
        return JSONResponse({"success": True, "count": count})
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
