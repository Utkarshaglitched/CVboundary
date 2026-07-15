const canvas = document.getElementById('drawCanvas');
const ctx = canvas.getContext('2d');
const clearBtn = document.getElementById('clearBtn');
const saveBtn = document.getElementById('saveBtn');
const dangerSideSelect = document.getElementById('dangerSide');

let backgroundImage = new Image();
let drawnPoints = [];
let isDrawing = false;
let frameLoaded = false;
let refreshTimer = null;

function normalizedPoints() {
  return drawnPoints.map((point) => ({
    x: point.x / canvas.width,
    y: point.y / canvas.height,
  }));
}

function denormalizePoints(points) {
  return points.map((point) => ({
    x: point.x * canvas.width,
    y: point.y * canvas.height,
  }));
}

function redraw() {
  if (!frameLoaded) {
    return;
  }
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(backgroundImage, 0, 0, canvas.width, canvas.height);

  if (drawnPoints.length >= 2) {
    ctx.strokeStyle = '#ff3333';
    ctx.lineWidth = 4;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(drawnPoints[0].x, drawnPoints[0].y);
    for (let index = 1; index < drawnPoints.length; index += 1) {
      ctx.lineTo(drawnPoints[index].x, drawnPoints[index].y);
    }
    ctx.stroke();
  }
}

function canvasPointFromEvent(event) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const clientX = event.touches ? event.touches[0].clientX : event.clientX;
  const clientY = event.touches ? event.touches[0].clientY : event.clientY;
  return {
    x: Math.max(0, Math.min(canvas.width, (clientX - rect.left) * scaleX)),
    y: Math.max(0, Math.min(canvas.height, (clientY - rect.top) * scaleY)),
  };
}

function startDrawing(event) {
  event.preventDefault();
  isDrawing = true;
  drawnPoints = [canvasPointFromEvent(event)];
  redraw();
}

function continueDrawing(event) {
  if (!isDrawing) {
    return;
  }
  event.preventDefault();
  const point = canvasPointFromEvent(event);
  const lastPoint = drawnPoints[drawnPoints.length - 1];
  const movedEnough = !lastPoint || Math.abs(lastPoint.x - point.x) > 0.5 || Math.abs(lastPoint.y - point.y) > 0.5;
  if (movedEnough) {
    drawnPoints.push(point);
    redraw();
  }
}

function stopDrawing(event) {
  if (!isDrawing) {
    return;
  }
  event.preventDefault();
  isDrawing = false;
}

async function loadFrame() {
  const nextImage = new Image();
  nextImage.src = `/api/settings/frame?ts=${Date.now()}`;
  await new Promise((resolve, reject) => {
    nextImage.onload = resolve;
    nextImage.onerror = reject;
  });

  backgroundImage = nextImage;
  canvas.width = backgroundImage.naturalWidth;
  canvas.height = backgroundImage.naturalHeight;
  frameLoaded = true;
  redraw();
}

async function loadSavedPerimeter() {
  const response = await fetch('/api/perimeter');
  const data = await response.json();
  if (data.danger_side && ['left', 'right'].includes(data.danger_side)) {
    dangerSideSelect.value = data.danger_side;
  }
  if (Array.isArray(data.points) && data.points.length >= 2) {
    drawnPoints = denormalizePoints(data.points);
    redraw();
  }
}

async function savePerimeter() {
  const points = normalizedPoints();
  if (points.length < 2) {
    alert('Draw at least two points for your perimeter line.');
    return;
  }

  const response = await fetch('/api/perimeter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ points, danger_side: dangerSideSelect.value }),
  });

  if (!response.ok) {
    const error = await response.json();
    alert(error.detail || 'Failed to save perimeter.');
    return;
  }

  alert('Perimeter saved.');
}

function clearDrawing() {
  drawnPoints = [];
  redraw();
}

function scheduleFrameRefresh() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer);
  }
  refreshTimer = window.setInterval(() => {
    loadFrame().catch(() => {});
  }, 250);
}

window.addEventListener('resize', redraw);
canvas.addEventListener('mousedown', startDrawing);
canvas.addEventListener('mousemove', continueDrawing);
canvas.addEventListener('mouseup', stopDrawing);
canvas.addEventListener('mouseleave', stopDrawing);

canvas.addEventListener('touchstart', startDrawing, { passive: false });
canvas.addEventListener('touchmove', continueDrawing, { passive: false });
canvas.addEventListener('touchend', stopDrawing, { passive: false });

clearBtn.addEventListener('click', clearDrawing);
saveBtn.addEventListener('click', savePerimeter);

loadFrame()
  .then(() => {
    loadSavedPerimeter();
    scheduleFrameRefresh();
  })
  .catch(() => alert('Could not load camera frame. Check that the camera is online.'));
