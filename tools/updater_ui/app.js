const statusPanel = document.querySelector("#statusPanel");
const statusText = document.querySelector("#statusText");
const percentText = document.querySelector("#percentText");
const progressBar = document.querySelector("#progressBar");
const detailText = document.querySelector("#detailText");
const repoText = document.querySelector("#repoText");
const stateBadge = document.querySelector("#stateBadge");
const closeButton = document.querySelector("#closeButton");
const stepNodes = [...document.querySelectorAll("[data-step]")];

let pollHandle = null;

function api() {
  return window.pywebview?.api;
}

function applyStatus(status) {
  const percent = Number(status.percent || 0);
  statusPanel.dataset.state = status.state || "idle";
  document.body.dataset.state = status.state || "idle";
  statusText.textContent = status.message || "Checking for updates...";
  percentText.textContent = `${Math.round(percent)}%`;
  progressBar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
  detailText.textContent = status.detail || "";
  stateBadge.textContent = stateLabel(status.state || "idle");
  updateSteps(percent, status.state || "idle");

  if ((status.detail || "").includes(":\\") || (status.detail || "").startsWith("/")) {
    repoText.textContent = status.detail;
  }

  closeButton.disabled = !status.done;

  if (status.done && pollHandle) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
}

function stateLabel(state) {
  return {
    idle: "Starting",
    running: "Checking",
    done: "Current",
    updated: "Updated",
    skipped: "Skipped",
    error: "Failed",
  }[state] || state;
}

function updateSteps(percent, state) {
  const activeIndex =
    state === "error" ? -1 : percent >= 76 ? 2 : percent >= 58 ? 1 : percent >= 25 ? 0 : -1;
  stepNodes.forEach((node, index) => {
    node.classList.toggle("is-active", index === activeIndex && state === "running");
    node.classList.toggle("is-done", index < activeIndex || state === "done" || state === "updated");
  });
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
