const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => document.querySelectorAll(selector);

const form = $("#downloadForm");
const urlField = $("#urlField");
const urlInput = $("#urlInput");
const qualityField = $("#qualityField");
const qualitySelect = $("#qualitySelect");
const qualityDropdown = $("#qualityDropdown");
const qualityButton = $("#qualityButton");
const qualityButtonText = $("#qualityButtonText");
const qualityOptions = $$(".select-menu [role='option']");
const bitrateSelect = $("#bitrateSelect");
const metadataCheck = $("#metadataCheck");
const thumbnailCheck = $("#thumbnailCheck");
const embedThumbnailCheck = $("#embedThumbnailCheck");
const subtitlesCheck = $("#subtitlesCheck");
const autoUpdateAppCheck = $("#autoUpdateAppCheck");
const previewButton = $("#previewButton");
const previewPanel = $("#previewPanel");
const previewThumb = $("#previewThumb");
const previewTitle = $("#previewTitle");
const previewMeta = $("#previewMeta");
const previewQualities = $("#previewQualities");
const downloadButton = $("#downloadButton");
const cancelButton = $("#cancelButton");
const openCurrentButton = $("#openCurrentButton");
const openFolderButton = $("#openFolderButton");
const folderButton = $("#folderButton");
const folderText = $("#folderText");
const ffmpegNotice = $("#ffmpegNotice");
const versionText = $("#versionText");
const appUpdateText = $("#appUpdateText");
const updateAppButton = $("#updateAppButton");
const updateYtdlpButton = $("#updateYtdlpButton");
const queueList = $("#queueList");
const queueEmpty = $("#queueEmpty");
const clearQueueButton = $("#clearQueueButton");
const historyList = $("#historyList");
const historyEmpty = $("#historyEmpty");
const clearHistoryButton = $("#clearHistoryButton");
const statusPanel = $(".status");
const statusText = $("#statusText");
const percentText = $("#percentText");
const progressBar = $("#progressBar");
const speedText = $("#speedText");
const etaText = $("#etaText");
const fileText = $("#fileText");
const errorDetails = $("#errorDetails");
const errorText = $("#errorText");

let pollHandle = null;
let activeDownload = null;
let downloadHistory = [];
let queueItems = [];
let currentPath = "";
let saveSettingsHandle = null;

const youtubeUrlPattern =
  /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)\/.+/i;
const terminalStates = new Set(["done", "error", "cancelled"]);
const idleStatus = {
  state: "idle",
  message: "Ready",
  percent: 0,
  speed: "",
  eta: "",
  file: "",
  path: "",
  rawError: "",
};

function pyApi() {
  return window.pywebview?.api;
}

function selectedFormat() {
  return $("input[name='format']:checked").value;
}

function parseUrls() {
  return urlInput.value
    .split(/\s+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function selectedQualityLabel() {
  return selectedFormat() === "mp3" ? `${bitrateSelect.value} kbps` : qualityButtonText.textContent;
}

function selectedOptions() {
  return {
    mp3Bitrate: bitrateSelect.value,
    subtitles: subtitlesCheck.checked,
    saveThumbnail: thumbnailCheck.checked,
    embedThumbnail: embedThumbnailCheck.checked,
    embedMetadata: metadataCheck.checked,
    autoUpdateApp: autoUpdateAppCheck.checked,
  };
}

function selectedSettings() {
  return {
    format: selectedFormat(),
    quality: qualitySelect.value,
    ...selectedOptions(),
  };
}

function setBusy(isBusy) {
  downloadButton.disabled = isBusy;
  previewButton.disabled = isBusy;
  cancelButton.disabled = !isBusy;
  downloadButton.querySelector("span").textContent = isBusy
    ? "Downloading..."
    : "Start queue";
}

function setUrlError(message) {
  const errorTextNode = $("#urlError");
  urlField.classList.toggle("has-error", Boolean(message));
  urlInput.setAttribute("aria-invalid", String(Boolean(message)));
  errorTextNode.textContent = message;
}

function validateUrls(urls = parseUrls()) {
  if (!urls.length) {
    setUrlError("Paste at least one YouTube link.");
    return false;
  }

  const invalidUrl = urls.find((url) => !youtubeUrlPattern.test(url));
  if (invalidUrl) {
    setUrlError(`Invalid YouTube link: ${invalidUrl}`);
    return false;
  }

  setUrlError("");
  return true;
}

function applyStatus(status) {
  const percent = Number(status.percent || 0);
  const state = status.state || "idle";
  const isUrlError = state === "error" && status.errorField === "url";
  const isRunning = state === "running" || state === "cancelling";

  if (isUrlError) {
    setUrlError(status.message || "This YouTube link could not be reached.");
  }

  currentPath = status.path || currentPath;
  statusPanel.dataset.state = isUrlError ? "idle" : state;
  statusText.textContent = isUrlError ? "Ready" : status.message || "Ready";
  percentText.textContent = `${Math.round(percent)}%`;
  progressBar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
  speedText.textContent = status.speed || "";
  etaText.textContent = status.eta ? `ETA ${status.eta}` : "";
  fileText.textContent = isUrlError ? "" : status.file || "";
  openCurrentButton.disabled = !currentPath || state !== "done";

  const technicalError = state === "error" && !isUrlError && (status.rawError || status.message);
  errorDetails.hidden = !technicalError;
  errorText.textContent = technicalError || "";

  setBusy(isRunning);

  if (terminalStates.has(state)) {
    finishActiveDownload(status);
  }

  if (!isRunning && !activeDownload && !nextPendingItem() && pollHandle) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
}

function finishActiveDownload(status) {
  if (!activeDownload || activeDownload.completed) return;

  activeDownload.completed = true;
  activeDownload.state = status.state;
  activeDownload.file = status.file || "";
  activeDownload.path = status.path || "";
  activeDownload.error = status.state === "error" ? status.message || "Download failed." : "";

  if (status.state === "done") {
    recordDownload(status, activeDownload);
  }

  activeDownload = null;
  renderQueue();

  if (nextPendingItem()) {
    setTimeout(startNextQueuedDownload, 250);
  }
}

async function loadHistory() {
  const api = pyApi();
  if (!api) {
    downloadHistory = [];
    renderHistory();
    return;
  }

  const result = await api.get_history();
  downloadHistory = result.ok ? result.history : [];
  renderHistory();
}

function renderHistory() {
  historyList.innerHTML = "";
  historyEmpty.hidden = downloadHistory.length > 0;
  clearHistoryButton.disabled = downloadHistory.length === 0;

  downloadHistory.forEach((item) => {
    historyList.append(createHistoryRow(item));
  });
}

function createHistoryRow(item) {
  const row = document.createElement("article");
  row.className = "history-item";

  const title = document.createElement("strong");
  title.textContent = item.file || "Download finished";

  const details = document.createElement("span");
  details.textContent = `${item.format} - ${item.quality} - ${item.time}`;

  const actions = document.createElement("div");
  actions.className = "history-actions";

  const openButton = document.createElement("button");
  openButton.type = "button";
  openButton.textContent = "Open";
  openButton.disabled = !item.path;
  openButton.addEventListener("click", () => pyApi()?.open_path(item.path));

  const folderButtonNode = document.createElement("button");
  folderButtonNode.type = "button";
  folderButtonNode.textContent = "Folder";
  folderButtonNode.disabled = !item.path;
  folderButtonNode.addEventListener("click", () => pyApi()?.open_folder(item.path));

  actions.append(openButton, folderButtonNode);
  row.append(title, details, actions);
  return row;
}

async function recordDownload(status, item) {
  const historyItem = {
    file: status.file || "Download finished",
    format: item.format.toUpperCase(),
    quality: item.qualityLabel,
    time: new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
    path: status.path || "",
    url: item.url,
  };

  const result = await pyApi().add_history(historyItem);
  downloadHistory = result.ok ? result.history : [historyItem, ...downloadHistory].slice(0, 20);
  renderHistory();
}

function renderQueue() {
  queueList.innerHTML = "";
  queueEmpty.hidden = queueItems.length > 0;
  clearQueueButton.disabled = !queueItems.some((item) => item.state !== "running");

  queueItems.forEach((item) => {
    queueList.append(createQueueRow(item));
  });
}

function createQueueRow(item) {
  const row = document.createElement("article");
  row.className = "queue-item";
  row.dataset.state = item.state;

  const title = document.createElement("strong");
  title.textContent = item.file || item.url;

  const details = document.createElement("span");
  details.textContent = `${queueStateLabel(item.state)} - ${item.format.toUpperCase()} - ${item.qualityLabel}`;

  row.append(title, details);
  return row;
}

function queueStateLabel(state) {
  return {
    pending: "Waiting",
    running: "Downloading",
    done: "Done",
    error: "Failed",
    cancelled: "Cancelled",
  }[state] || state;
}

function addUrlsToQueue(urls) {
  const settings = selectedSettings();
  const created = urls.map((url) => ({
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    url,
    format: settings.format,
    quality: settings.quality,
    qualityLabel: selectedQualityLabel(),
    options: selectedOptions(),
    state: "pending",
    file: "",
    path: "",
    error: "",
    completed: false,
  }));

  queueItems.push(...created);
  renderQueue();
}

function nextPendingItem() {
  return queueItems.find((item) => item.state === "pending");
}

async function startNextQueuedDownload() {
  if (activeDownload) return;

  const item = nextPendingItem();
  if (!item) {
    applyStatus(idleStatus);
    return;
  }

  const result = await pyApi().start_download(
    item.url,
    item.format,
    item.quality,
    item.options,
  );

  if (!result.ok) {
    item.state = "error";
    item.error = result.error || "Download failed.";
    renderQueue();
    applyStatus({
      state: "error",
      message: item.error,
      percent: 0,
      speed: "",
      eta: "",
      file: "",
      path: "",
      rawError: item.error,
    });
    setTimeout(startNextQueuedDownload, 250);
    return;
  }

  setUrlError("");
  activeDownload = item;
  currentPath = "";
  item.state = "running";
  item.completed = false;
  renderQueue();
  setBusy(true);
  await refreshStatus();

  if (!pollHandle) {
    pollHandle = setInterval(refreshStatus, 500);
  }
}

async function refreshStatus() {
  const api = pyApi();
  if (!api) return;
  const status = await api.get_status();
  applyStatus(status);
}

async function refreshConfig() {
  const config = await pyApi().get_config();
  folderText.textContent = config.downloadFolder;
  ffmpegNotice.hidden = Boolean(config.ffmpegAvailable);
  versionText.textContent = `yt-dlp ${config.ytdlpVersion}`;
  appUpdateText.textContent = appUpdateStatusText(config.appUpdate);
  updateAppButton.disabled = !config.appUpdate?.canUpdate;
  updateYtdlpButton.disabled = !config.canUpdateYtdlp;
  applySettings(config.settings || {});
}

function applySettings(settings) {
  const formatInput = $(`input[name='format'][value='${settings.format || "mp4"}']`);
  if (formatInput) formatInput.checked = true;
  setQuality(settings.quality || "1080");
  bitrateSelect.value = settings.mp3Bitrate || "320";
  subtitlesCheck.checked = Boolean(settings.subtitles);
  thumbnailCheck.checked = Boolean(settings.saveThumbnail);
  embedThumbnailCheck.checked = Boolean(settings.embedThumbnail);
  metadataCheck.checked = settings.embedMetadata !== false;
  autoUpdateAppCheck.checked = Boolean(settings.autoUpdateApp);
  syncQualityVisibility();
}

function scheduleSettingsSave() {
  clearTimeout(saveSettingsHandle);
  saveSettingsHandle = setTimeout(() => {
    pyApi()?.update_settings(selectedSettings());
  }, 150);
}

function appUpdateStatusText(info) {
  if (!info) return "";
  const details = [info.branch, info.commit].filter(Boolean).join(" @ ");
  if (info.canUpdate) {
    return details ? `App updates: ${details}` : "App updates: Git pull available";
  }
  return info.message || "App updates are not available in this install.";
}

async function runAppUpdate(isAutomatic = false) {
  updateAppButton.disabled = true;
  appUpdateText.textContent = isAutomatic
    ? "Checking app updates..."
    : "Pulling app updates...";

  const result = isAutomatic
    ? await pyApi()?.auto_update_app()
    : await pyApi()?.update_app();

  if (result?.skipped) {
    await refreshConfig();
    return;
  }

  appUpdateText.textContent = result?.ok
    ? `${result.message} Restart the app if files changed.`
    : result?.error || "Could not update the app.";
  setTimeout(refreshConfig, 3200);
}

function syncQualityVisibility() {
  const isMp3 = selectedFormat() === "mp3";
  qualityField.classList.toggle("is-disabled", isMp3);
  qualitySelect.disabled = isMp3;
  qualityButton.disabled = isMp3;
  bitrateSelect.disabled = !isMp3;
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

async function previewFirstUrl() {
  const urls = parseUrls();
  if (!validateUrls(urls)) {
    urlInput.focus();
    return;
  }

  previewButton.disabled = true;
  previewPanel.hidden = false;
  previewTitle.textContent = "Fetching preview...";
  previewMeta.textContent = "";
  previewQualities.textContent = "";
  previewThumb.removeAttribute("src");

  const result = await pyApi().fetch_info(urls[0]);
  previewButton.disabled = false;

  if (!result.ok) {
    setUrlError(result.error || "Could not fetch video info.");
    previewPanel.hidden = true;
    return;
  }

  const info = result.info || {};
  previewThumb.src = info.thumbnail || "";
  previewTitle.textContent = info.title || "Untitled";
  previewMeta.textContent = [info.channel, formatDuration(info.duration)].filter(Boolean).join(" - ");
  previewQualities.textContent = info.qualities?.length
    ? `Available: ${info.qualities.join(", ")}`
    : "";
}

function formatDuration(totalSeconds) {
  const value = Number(totalSeconds || 0);
  if (!value) return "";
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = value % 60;
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

$$("input[name='format']").forEach((input) => {
  input.addEventListener("change", () => {
    syncQualityVisibility();
    scheduleSettingsSave();
  });
});

[bitrateSelect, metadataCheck, thumbnailCheck, embedThumbnailCheck, subtitlesCheck, autoUpdateAppCheck].forEach((input) => {
  input.addEventListener("change", scheduleSettingsSave);
});

qualityButton.addEventListener("click", toggleQualityDropdown);

qualityOptions.forEach((option) => {
  option.addEventListener("click", () => {
    setQuality(option.dataset.value);
    scheduleSettingsSave();
  });
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
  previewPanel.hidden = true;
  if (urlField.classList.contains("has-error")) {
    validateUrls();
  }
});

folderButton.addEventListener("click", async () => {
  const result = await pyApi().set_download_folder();
  if (result.ok) {
    folderText.textContent = result.folder;
  }
});

openFolderButton.addEventListener("click", () => {
  pyApi()?.open_folder(currentPath || "");
});

openCurrentButton.addEventListener("click", () => {
  if (currentPath) {
    pyApi()?.open_path(currentPath);
  }
});

updateAppButton.addEventListener("click", () => {
  runAppUpdate(false);
});

updateYtdlpButton.addEventListener("click", async () => {
  updateYtdlpButton.disabled = true;
  versionText.textContent = "Updating yt-dlp...";
  const result = await pyApi()?.update_ytdlp();
  versionText.textContent = result?.ok
    ? result.message
    : result?.error || "Could not update yt-dlp.";
  setTimeout(refreshConfig, 2600);
});

previewButton.addEventListener("click", previewFirstUrl);

cancelButton.addEventListener("click", async () => {
  await pyApi()?.cancel_download();
  await refreshStatus();
});

clearQueueButton.addEventListener("click", () => {
  queueItems = queueItems.filter((item) => item.state === "running");
  renderQueue();
});

clearHistoryButton.addEventListener("click", async () => {
  downloadHistory = [];
  const api = pyApi();
  if (api) {
    await api.clear_history();
  }
  renderHistory();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const urls = parseUrls();
  if (!validateUrls(urls)) {
    applyStatus(idleStatus);
    urlInput.focus();
    return;
  }

  addUrlsToQueue(urls);
  await startNextQueuedDownload();
});

window.addEventListener("pywebviewready", async () => {
  syncQualityVisibility();
  renderQueue();
  await loadHistory();
  await refreshConfig();
  if (autoUpdateAppCheck.checked) {
    await runAppUpdate(true);
  }
  await refreshStatus();
});
