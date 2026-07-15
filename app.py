from __future__ import annotations

import json
import os
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import crud
import database
from camera import CameraManager
from detector import IntrusionDetector
from face_recognition import FaceRecognizer
from models import IntrusionLog
from streamer import Streamer

app = FastAPI(title="Surveillance Dashboard", version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

latest_intrusion_status = {"value": 0, "updated_at": None}


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
streamer = Streamer()
face_recognizer = FaceRecognizer()


def handle_intrusion(image_path: str, recognized_people: str) -> None:
    db = database.SessionLocal()
    try:
        crud.create_log(db, image_path=image_path, recognized_people=recognized_people)
    finally:
        db.close()
    _notify_alarm_board(1)


def update_intrusion_status(value: int) -> None:
    latest_intrusion_status["value"] = value
    latest_intrusion_status["updated_at"] = datetime.utcnow().isoformat()


detector = IntrusionDetector(
    face_recognizer=face_recognizer,
    on_intrusion=handle_intrusion,
    on_status_change=update_intrusion_status,
)
streamer.set_overlay_supplier(detector.get_detection_overlays)


@app.on_event("startup")
def startup_event() -> None:
    database.init_db()
    os.makedirs(config.CAPTURED_IMAGES_DIR, exist_ok=True)
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
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "camera_status": "Online" if camera.is_running else "Offline",
                "intrusions_today": count,
                "latest_person": latest.recognized_people if latest else "None",
                "system_status": detector.status,
            },
        )
    finally:
        db.close()


@app.get("/video_feed")
async def video_feed() -> StreamingResponse:
    return streamer.response()


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
        items = crud.list_logs(db, query=query, filter_kind=filter, sort_newest=sort_newest)
        return JSONResponse([
            {
                "id": entry.id,
                "timestamp": entry.timestamp,
                "image_url": f"/captures/{Path(entry.image_path).name}",
                "recognized_people": entry.recognized_people,
                "person_count": len([name for name in entry.recognized_people.split(",") if name.strip()]),
                "status": entry.status,
            }
            for entry in items
        ])
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
            "recognized_people": entry.recognized_people,
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
