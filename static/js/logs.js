async function loadLogs() {
  const query = document.getElementById('searchInput').value;
  const filter = document.getElementById('filterSelect').value;
  const sort = document.getElementById('sortSelect').value;
  const tbody = document.getElementById('logsBody');
  tbody.innerHTML = '<tr><td colspan="6" class="text-muted">Identifying faces...</td></tr>';

  const response = await fetch(`/api/logs?query=${encodeURIComponent(query)}&filter=${encodeURIComponent(filter)}&sort=${encodeURIComponent(sort)}`);
  const logs = await response.json();
  tbody.innerHTML = '';
  logs.forEach((log) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${log.id}</td>
      <td><a href="#" data-image="${log.image_url}" data-bs-toggle="modal" data-bs-target="#imageModal"><img src="${log.image_url}" class="img-thumbnail" style="max-width: 120px;" alt="Intrusion preview" /></a></td>
      <td>${log.timestamp}</td>
      <td>${log.recognized_people} <span class="badge bg-secondary">${log.person_count}</span></td>
      <td>${log.status}</td>
      <td><button class="btn btn-sm btn-outline-danger" onclick="deleteLog(${log.id})">Delete</button></td>
    `;
    tbody.appendChild(row);
  });
}

async function deleteLog(id) {
  await fetch(`/api/log/${id}`, { method: 'DELETE' });
  await loadLogs();
}

document.getElementById('searchInput').addEventListener('input', loadLogs);
document.getElementById('filterSelect').addEventListener('change', loadLogs);
document.getElementById('sortSelect').addEventListener('change', loadLogs);
document.addEventListener('click', (event) => {
  const target = event.target;
  const link = target instanceof HTMLElement ? target.closest('a[data-image]') : null;
  if (!link) {
    return;
  }

  event.preventDefault();
  const modalImage = document.getElementById('modalImage');
  modalImage.src = link.dataset.image;
  const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('imageModal'));
  modal.show();
});

loadLogs();
