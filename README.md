# CV Boundary

CV Boundary is a Python-based surveillance dashboard that uses computer vision to detect people crossing a defined boundary and log intrusion events.

## Features
- Real-time person detection with YOLO
- Boundary intrusion monitoring
- Face recognition for known individuals
- Web dashboard for viewing logs and captured images
- SQLite-backed intrusion logging

## Tech Stack
- Python
- FastAPI
- OpenCV
- Ultralytics YOLO
- SQLAlchemy

## Getting Started
1. Install dependencies from requirements.txt
2. Place the YOLO model file in the MODELS folder
3. Run the app with Python

```bash
python app.py
```
