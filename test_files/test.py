from ultralytics import YOLO
import cv2

# Load local model
model = YOLO("best.pt")

# Optional: move to GPU
model.to("cuda")

# Run inference
cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()

    if not ret:
        break

    results = model(
        frame,
        device=0,
        conf=0.25,
        verbose=False
    )

    annotated = results[0].plot()

    cv2.imshow("PPE", annotated)

    if cv2.waitKey(1) == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()