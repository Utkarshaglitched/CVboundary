from pathlib import Path

import cv2
from ultralytics import YOLO

# Load model
model_path = Path(__file__).resolve().parent / "MODELS" / "yolo11x.pt"
model = YOLO(str(model_path))
model.to("cuda")

# Webcam
cap = cv2.VideoCapture(0)

# Fullscreen window
cv2.namedWindow("YOLO", cv2.WINDOW_NORMAL)
cv2.setWindowProperty(
    "YOLO",
    cv2.WND_PROP_FULLSCREEN,
    cv2.WINDOW_FULLSCREEN
)

while True:

    ret, frame = cap.read()

    if not ret:
        break

    height, width = frame.shape[:2]

    # Vertical Boundary
    boundary_x = width // 4

    cv2.line(
        frame,
        (boundary_x, 0),
        (boundary_x, height),
        (0, 0, 255),
        3
    )

    # Run YOLO
    results = model(frame, verbose=False)

    danger = False

    for result in results:

        for box in result.boxes:

            # Detect only persons
            if int(box.cls[0]) != 0:
                continue

            conf = float(box.conf[0])

            # Ignore weak detections
            if conf < 0.5:
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0])

            # Draw Bounding Box
            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (255, 0, 0),
                2
            )

            # Draw Confidence
            cv2.putText(
                frame,
                f"Person {conf:.2f}",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 0, 0),
                2
            )

            # Bottom-center of person (foot point)
            foot_x = (x1 + x2) // 2
            foot_y = y2

            cv2.circle(
                frame,
                (foot_x, foot_y),
                5,
                (0, 255, 0),
                -1
            )

            # Check intrusion
            if foot_x < boundary_x:

                danger = True

                cv2.putText(
                    frame,
                    "DANGER",
                    (x1, y2 + 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2
                )

            else:

                cv2.putText(
                    frame,
                    "SAFE",
                    (x1, y2 + 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2
                )

    # Global Banner
    if danger:

        cv2.rectangle(frame, (0, 0), (width, 70), (0, 0, 255), -1)

        cv2.putText(
            frame,
            "INTRUSION DETECTED",
            (20, 45),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (255, 255, 255),
            3
        )

    else:

        cv2.rectangle(frame, (0, 0), (width, 70), (0, 150, 0), -1)

        cv2.putText(
            frame,
            "AREA SAFE",
            (20, 45),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (255, 255, 255),
            3
        )

    cv2.imshow("YOLO", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()