const statusPanel = document.querySelector("#statusPanel");
const statusText = document.querySelector("#statusText");
const percentText = document.querySelector("#percentText");
const progressBar = document.querySelector("#progressBar");
const detailText = document.querySelector("#detailText");
const closeButton = document.querySelector("#closeButton");

let pollHandle = null;

function api() {
  return window.pywebview?.api;
}

function applyStatus(status) {
  const percent = Number(status.percent || 0);
  statusPanel.dataset.state = status.state || "idle";
  statusText.textContent = status.message || "Checking for updates...";
  percentText.textContent = `${Math.round(percent)}%`;
  progressBar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
  detailText.textContent = status.detail || "";
  closeButton.disabled = !status.done;

  if (status.done && pollHandle) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
}

async function refreshStatus() {
  const bridge = api();
  if (!bridge) return;
  applyStatus(await bridge.get_status());
}

closeButton.addEventListener("click", () => {
  api()?.close();
});

window.addEventListener("pywebviewready", async () => {
  await api().start();
  await refreshStatus();
  pollHandle = setInterval(refreshStatus, 250);
});
