const form = document.querySelector("#downloadForm");
const urlField = document.querySelector("#urlField");
const urlInput = document.querySelector("#urlInput");
const qualityField = document.querySelector("#qualityField");
const qualitySelect = document.querySelector("#qualitySelect");
const qualityDropdown = document.querySelector("#qualityDropdown");
const qualityButton = document.querySelector("#qualityButton");
const qualityButtonText = document.querySelector("#qualityButtonText");
const qualityOptions = document.querySelectorAll(".select-menu [role='option']");
const downloadButton = document.querySelector("#downloadButton");
const folderButton = document.querySelector("#folderButton");
const folderText = document.querySelector("#folderText");
const ffmpegNotice = document.querySelector("#ffmpegNotice");
const historyList = document.querySelector("#historyList");
const historyEmpty = document.querySelector("#historyEmpty");
const clearHistoryButton = document.querySelector("#clearHistoryButton");
const statusPanel = document.querySelector(".status");
const statusText = document.querySelector("#statusText");
const percentText = document.querySelector("#percentText");
const progressBar = document.querySelector("#progressBar");
const speedText = document.querySelector("#speedText");
const etaText = document.querySelector("#etaText");
const fileText = document.querySelector("#fileText");

let pollHandle = null;
let activeDownload = null;
let lastRecordedDownload = "";
let downloadHistory = [];
const youtubeUrlPattern =
  /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)\/.+/i;

function selectedFormat() {
  return document.querySelector("input[name='format']:checked").value;
}

function setBusy(isBusy) {
  downloadButton.disabled = isBusy;
  downloadButton.querySelector("span").textContent = isBusy
    ? "Downloading..."
    : "Start download";
}

function setUrlError(message) {
  const errorText = document.querySelector("#urlError");
  urlField.classList.toggle("has-error", Boolean(message));
  urlInput.setAttribute("aria-invalid", String(Boolean(message)));
  errorText.textContent = message;
}

function validateUrl() {
  const value = urlInput.value.trim();

  if (!value) {
    setUrlError("Paste a YouTube link first.");
    return false;
  }

  if (!youtubeUrlPattern.test(value)) {
    setUrlError("Enter a valid YouTube link.");
    return false;
  }

  setUrlError("");
  return true;
}

function applyStatus(status) {
  const percent = Number(status.percent || 0);
  const state = status.state || "idle";
  const isUrlError = state === "error" && status.errorField === "url";

  if (isUrlError) {
    setUrlError(status.message || "This YouTube link could not be reached.");
  }

  statusPanel.dataset.state = isUrlError ? "idle" : state;
  statusText.textContent = isUrlError ? "Ready" : status.message || "Ready";
  percentText.textContent = `${Math.round(percent)}%`;
  progressBar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
  speedText.textContent = status.speed || "";
  etaText.textContent = status.eta ? `ETA ${status.eta}` : "";
  fileText.textContent = isUrlError ? "" : status.file || "";

  const isRunning = status.state === "running";
  setBusy(isRunning);

  if (state === "done") {
    recordDownload(status);
  }

  if (!isRunning && pollHandle) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
}

async function loadHistory() {
  if (!window.pywebview?.api) {
    downloadHistory = [];
    renderHistory();
    return;
  }

  const result = await window.pywebview.api.get_history();
  downloadHistory = result.ok ? result.history : [];
  renderHistory();
}

function renderHistory() {
  historyList.innerHTML = "";
  historyEmpty.hidden = downloadHistory.length > 0;
  clearHistoryButton.disabled = downloadHistory.length === 0;

  downloadHistory.forEach((item) => {
    const row = document.createElement("article");
    row.className = "history-item";

    const title = document.createElement("strong");
    title.textContent = item.file || "Download finished";

    const details = document.createElement("span");
    details.textContent = `${item.format} - ${item.quality} - ${item.time}`;

    row.append(title, details);
    historyList.append(row);
  });
}

async function recordDownload(status) {
  if (!activeDownload) return;

  const signature = `${activeDownload.startedAt}-${status.file || "done"}`;
  if (signature === lastRecordedDownload) return;

  lastRecordedDownload = signature;
  const item = {
    file: status.file || "Download finished",
    format: activeDownload.format.toUpperCase(),
    quality: activeDownload.quality,
    time: new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
  };

  activeDownload = null;
  const result = await window.pywebview.api.add_history(item);
  downloadHistory = result.ok ? result.history : [item, ...downloadHistory].slice(0, 20);
  renderHistory();
}

async function refreshStatus() {
  if (!window.pywebview?.api) return;
  const status = await window.pywebview.api.get_status();
  applyStatus(status);
}

async function refreshConfig() {
  const config = await window.pywebview.api.get_config();
  folderText.textContent = config.downloadFolder;
  ffmpegNotice.hidden = Boolean(config.ffmpegAvailable);
}

function syncQualityVisibility() {
  const isMp3 = selectedFormat() === "mp3";
  qualityField.classList.toggle("is-disabled", isMp3);
  qualitySelect.disabled = isMp3;
  qualityButton.disabled = isMp3;
  closeQualityDropdown();
}

function closeQualityDropdown() {
  qualityDropdown.classList.remove("is-open");
  qualityButton.setAttribute("aria-expanded", "false");
}

function toggleQualityDropdown() {
  if (qualityButton.disabled) return;
  const isOpen = qualityDropdown.classList.toggle("is-open");
  qualityButton.setAttribute("aria-expanded", String(isOpen));
}

function setQuality(value) {
  const option = [...qualityOptions].find((item) => item.dataset.value === value);
  if (!option) return;

  qualitySelect.value = value;
  qualityButtonText.textContent = option.querySelector("span").textContent;
  qualityOptions.forEach((item) => {
    item.setAttribute("aria-selected", String(item === option));
  });
  closeQualityDropdown();
}

document.querySelectorAll("input[name='format']").forEach((input) => {
  input.addEventListener("change", syncQualityVisibility);
});

qualityButton.addEventListener("click", toggleQualityDropdown);

qualityOptions.forEach((option) => {
  option.addEventListener("click", () => setQuality(option.dataset.value));
});

document.addEventListener("click", (event) => {
  if (!qualityDropdown.contains(event.target)) {
    closeQualityDropdown();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeQualityDropdown();
  }
});

urlInput.addEventListener("input", () => {
  if (urlField.classList.contains("has-error")) {
    validateUrl();
  }
});

folderButton.addEventListener("click", async () => {
  const result = await window.pywebview.api.set_download_folder();
  if (result.ok) {
    folderText.textContent = result.folder;
  }
});

clearHistoryButton.addEventListener("click", async () => {
  downloadHistory = [];
  activeDownload = null;
  lastRecordedDownload = "";
  if (window.pywebview?.api) {
    await window.pywebview.api.clear_history();
  }
  renderHistory();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (!validateUrl()) {
    applyStatus({
      state: "idle",
      message: "Ready",
      percent: 0,
      speed: "",
      eta: "",
      file: "",
    });
    urlInput.focus();
    return;
  }

  const result = await window.pywebview.api.start_download(
    urlInput.value,
    selectedFormat(),
    qualitySelect.value,
  );

  if (!result.ok) {
    if (result.errorField === "url") {
      setUrlError(result.error);
    } else {
      applyStatus({
        state: "error",
        message: result.error,
        percent: 0,
        speed: "",
        eta: "",
        file: "",
      });
    }
    return;
  }

  setUrlError("");
  activeDownload = {
    url: urlInput.value.trim(),
    format: selectedFormat(),
    quality:
      selectedFormat() === "mp3" ? "320 kbps" : qualityButtonText.textContent,
    startedAt: Date.now(),
  };
  lastRecordedDownload = "";
  setBusy(true);
  await refreshStatus();
  pollHandle = setInterval(refreshStatus, 500);
});

window.addEventListener("pywebviewready", async () => {
  syncQualityVisibility();
  await loadHistory();
  await refreshConfig();
  await refreshStatus();
});
