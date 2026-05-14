from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import webview
import yt_dlp
from yt_dlp import YoutubeDL


IS_FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
UI_DIR = RESOURCE_DIR / "ui"
DOWNLOAD_DIR = APP_DIR / "downloads"
HISTORY_FILE = APP_DIR / "history.json"
CONFIG_FILE = APP_DIR / "config.json"
HISTORY_LIMIT = 20
DEFAULT_CONFIG: dict[str, Any] = {
    "downloadFolder": str(DOWNLOAD_DIR),
    "format": "mp4",
    "quality": "1080",
    "mp3Bitrate": "320",
    "subtitles": False,
    "saveThumbnail": False,
    "embedThumbnail": False,
    "embedMetadata": True,
    "autoUpdateApp": False,
}
INITIAL_PROGRESS: dict[str, Any] = {
    "state": "idle",
    "message": "Ready",
    "percent": 0,
    "speed": "",
    "eta": "",
    "file": "",
    "path": "",
    "errorField": "",
    "rawError": "",
}
URL_ERROR_MARKERS = (
    "unable to download webpage",
    "unable to extract",
    "video unavailable",
    "private video",
    "this video is unavailable",
    "unsupported url",
    "not a valid url",
    "http error 404",
    "http error 403",
    "network is unreachable",
    "name resolution",
    "failed to resolve",
    "temporary failure in name resolution",
)
YOUTUBE_URL_RE = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)/.+",
    re.IGNORECASE,
)


class DownloadCancelled(Exception):
    """Raised internally when the user cancels an active download."""


class DownloaderApi:
    def __init__(self) -> None:
        self._config_file = CONFIG_FILE
        self._config = self._read_config()
        self._output_dir = Path(self._config["downloadFolder"])
        self._output_dir.mkdir(exist_ok=True)
        self._history_file = HISTORY_FILE
        self._progress = dict(INITIAL_PROGRESS)
        self._lock = threading.Lock()
        self._cancel_event: threading.Event | None = None
        self._window: webview.Window | None = None

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._progress)

    def set_download_folder(self) -> dict[str, Any]:
        if self._window is None:
            return {"ok": False, "error": "Window is not ready yet."}

        selected = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not selected:
            return {"ok": False, "error": "No folder selected."}

        self._output_dir = Path(selected[0])
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._config["downloadFolder"] = str(self._output_dir)
        self._write_config()
        return {"ok": True, "folder": str(self._output_dir)}

    def get_config(self) -> dict[str, Any]:
        repo_info = self._repo_info()
        return {
            "downloadFolder": str(self._output_dir),
            "historyFile": str(self._history_file),
            "ffmpegAvailable": shutil.which("ffmpeg") is not None,
            "ytdlpVersion": yt_dlp.version.__version__,
            "canUpdateYtdlp": not IS_FROZEN,
            "appUpdate": repo_info,
            "settings": dict(self._config),
        }

    def update_app(self) -> dict[str, Any]:
        repo_info = self._repo_info()
        if not repo_info["canUpdate"]:
            return {"ok": False, "error": repo_info["message"]}

        status = self._run_git(["status", "--porcelain"])
        if not status["ok"]:
            return status
        if status["stdout"].strip():
            return {
                "ok": False,
                "error": "The working tree has local changes. Commit or stash them before pulling updates.",
            }

        result = self._run_git(["pull", "--ff-only"])
        if not result["ok"]:
            return result

        output = (result["stdout"] or result["stderr"] or "Already up to date.").strip()
        return {
            "ok": True,
            "message": output[-800:],
            "restartRequired": True,
            "appUpdate": self._repo_info(),
        }

    def auto_update_app(self) -> dict[str, Any]:
        if not self._config.get("autoUpdateApp"):
            return {"ok": True, "skipped": True, "message": "Auto-update is off."}
        return self.update_app()

    def update_ytdlp(self) -> dict[str, Any]:
        if IS_FROZEN:
            return {
                "ok": False,
                "error": "Install a newer app build to update yt-dlp.",
            }

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except Exception as exc:
            return {"ok": False, "error": self._clean_error(str(exc))}

        output = (result.stdout or "") + "\n" + (result.stderr or "")
        if result.returncode != 0:
            return {"ok": False, "error": self._clean_error(output)}

        return {
            "ok": True,
            "message": "yt-dlp updated. Restart the app to use the new version.",
        }

    def update_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        self._config = self._clean_config({**self._config, **(settings or {})})
        self._output_dir = Path(self._config["downloadFolder"])
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._write_config()
        return {"ok": True, "settings": dict(self._config)}

    def fetch_info(self, url: str) -> dict[str, Any]:
        url = (url or "").strip()
        if not YOUTUBE_URL_RE.match(url):
            return {
                "ok": False,
                "error": "Enter a valid YouTube URL.",
                "errorField": "url",
            }

        try:
            with YoutubeDL(
                {
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "skip_download": True,
                }
            ) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            return {
                "ok": False,
                "error": self._clean_error(str(exc)),
                "errorField": "url" if self._is_url_error(str(exc)) else "",
            }

        return {"ok": True, "info": self._clean_info(info)}

    def get_history(self) -> dict[str, Any]:
        return {"ok": True, "history": self._read_history()}

    def add_history(self, item: dict[str, Any]) -> dict[str, Any]:
        history = self._read_history()
        history.insert(0, self._clean_history_item(item))
        history = history[:HISTORY_LIMIT]
        self._write_history(history)
        return {"ok": True, "history": history}

    def clear_history(self) -> dict[str, Any]:
        self._write_history([])
        return {"ok": True, "history": []}

    def open_path(self, path: str) -> dict[str, Any]:
        target = Path(path or "")
        if not target.exists():
            return {"ok": False, "error": "File no longer exists."}

        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception as exc:
            return {"ok": False, "error": self._clean_error(str(exc))}
        return {"ok": True}

    def open_folder(self, path: str = "") -> dict[str, Any]:
        target = Path(path or self._output_dir)
        folder = target if target.is_dir() else target.parent
        if not folder.exists():
            return {"ok": False, "error": "Folder no longer exists."}

        try:
            if target.is_file() and sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(target)])
            else:
                os.startfile(str(folder))  # type: ignore[attr-defined]
        except Exception as exc:
            return {"ok": False, "error": self._clean_error(str(exc))}
        return {"ok": True}

    def start_download(
        self,
        url: str,
        media_type: str,
        quality: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = (url or "").strip()
        media_type = (media_type or "mp4").lower()
        quality = (quality or "1080").lower()
        options = options or {}

        if not YOUTUBE_URL_RE.match(url):
            return {
                "ok": False,
                "error": "Enter a valid YouTube URL.",
                "errorField": "url",
            }

        if media_type not in {"mp3", "mp4"}:
            return {"ok": False, "error": "Choose MP3 or MP4."}

        if self.get_status()["state"] in {"running", "cancelling"}:
            return {"ok": False, "error": "A download is already running."}

        cancel_event = threading.Event()
        with self._lock:
            self._cancel_event = cancel_event

        thread = threading.Thread(
            target=self._download_worker,
            args=(url, media_type, quality, options, cancel_event),
            daemon=True,
        )
        thread.start()
        return {"ok": True}

    def cancel_download(self) -> dict[str, Any]:
        with self._lock:
            state = self._progress.get("state")
            cancel_event = self._cancel_event
            if state not in {"running", "cancelling"} or cancel_event is None:
                return {"ok": False, "error": "No active download to cancel."}
            cancel_event.set()
            self._progress.update(
                state="cancelling",
                message="Cancelling download...",
                speed="",
                eta="",
            )
        return {"ok": True}

    def _set_progress(self, **updates: Any) -> None:
        with self._lock:
            self._progress.update(updates)

    def _download_worker(
        self,
        url: str,
        media_type: str,
        quality: str,
        options: dict[str, Any],
        cancel_event: threading.Event,
    ) -> None:
        self._set_running("Preparing download...", percent=0)

        try:
            with YoutubeDL(self._build_options(media_type, quality, options)) as ydl:
                info = ydl.extract_info(url, download=True)
                final_file = self._final_file(ydl, info)
            if cancel_event.is_set():
                raise DownloadCancelled()
            self._set_done(final_file)
        except DownloadCancelled:
            self._set_cancelled()
        except Exception as exc:
            self._set_error(str(exc))
        finally:
            with self._lock:
                if self._cancel_event is cancel_event:
                    self._cancel_event = None

    def _build_options(
        self,
        media_type: str,
        quality: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        output_template = str(self._output_dir / "%(title).180B [%(id)s].%(ext)s")
        postprocessors: list[dict[str, Any]] = []

        base_options: dict[str, Any] = {
            "outtmpl": output_template,
            "progress_hooks": [self._progress_hook],
            "noplaylist": True,
            "windowsfilenames": True,
            "restrictfilenames": False,
            "quiet": True,
            "no_warnings": True,
        }

        if options.get("subtitles"):
            base_options.update(
                {
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": ["en", "en.*"],
                    "subtitlesformat": "srt/best",
                }
            )

        if options.get("saveThumbnail") or options.get("embedThumbnail"):
            base_options["writethumbnail"] = True

        if options.get("embedMetadata"):
            postprocessors.append({"key": "FFmpegMetadata"})

        if options.get("embedThumbnail"):
            postprocessors.append({"key": "EmbedThumbnail"})

        if media_type == "mp3":
            bitrate = self._clean_mp3_bitrate(options.get("mp3Bitrate"))
            return {
                **base_options,
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": bitrate,
                    },
                    *postprocessors,
                ],
            }

        if quality == "best":
            format_selector = "bestvideo*+bestaudio/best"
        else:
            max_height = "720" if quality == "720" else "1080"
            format_selector = (
                f"bestvideo*[height<={max_height}]+bestaudio/"
                f"best[height<={max_height}]/best"
            )

        return {
            **base_options,
            "format": format_selector,
            "merge_output_format": "mp4",
            "postprocessors": postprocessors,
        }

    def _progress_hook(self, data: dict[str, Any]) -> None:
        status = data.get("status")

        if self._is_cancel_requested():
            raise DownloadCancelled()

        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            percent = round(downloaded / total * 100, 1) if total else 0
            speed = self._format_speed(data.get("speed"))
            self._set_running(
                "Downloading...",
                percent=percent,
                speed=speed,
                eta=self._format_eta(data.get("eta")),
                file=Path(data.get("filename") or "").name,
                path=str(Path(data.get("filename") or "")),
            )
            return

        if status == "finished":
            self._set_running(
                "Processing file...",
                percent=100,
                file=Path(data.get("filename") or "").name,
                path=str(Path(data.get("filename") or "")),
            )

    def _final_file(self, ydl: YoutubeDL, info: dict[str, Any] | None) -> dict[str, str]:
        if not info:
            return {"file": "", "path": ""}

        requested = info.get("requested_downloads") if isinstance(info, dict) else None
        if isinstance(requested, list):
            for item in requested:
                if not isinstance(item, dict):
                    continue
                file_path = item.get("filepath")
                if file_path and Path(file_path).exists():
                    path = Path(file_path)
                    return {"file": path.name, "path": str(path)}

        try:
            path = ydl.prepare_filename(info)
        except Exception:
            return {"file": "", "path": ""}

        source_path = Path(path)
        candidates = list(self._output_dir.glob(f"{source_path.stem}.*"))
        if candidates:
            newest = max(candidates, key=lambda item: item.stat().st_mtime)
            return {"file": newest.name, "path": str(newest)}
        return {"file": source_path.name, "path": str(source_path)}

    def _read_config(self) -> dict[str, Any]:
        try:
            if not self._config_file.exists():
                return dict(DEFAULT_CONFIG)
            data = json.loads(self._config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(DEFAULT_CONFIG)
        if not isinstance(data, dict):
            return dict(DEFAULT_CONFIG)
        return self._clean_config({**DEFAULT_CONFIG, **data})

    def _write_config(self) -> None:
        self._config_file.write_text(
            json.dumps(self._config, indent=2),
            encoding="utf-8",
        )

    def _repo_info(self) -> dict[str, Any]:
        repo_root = self._find_repo_root(APP_DIR)
        git_path = shutil.which("git")
        if repo_root is None:
            return {
                "canUpdate": False,
                "message": "App updates via GitHub pull require this app to run from a Git checkout.",
                "repoRoot": "",
                "remote": "",
                "branch": "",
                "commit": "",
            }
        if git_path is None:
            return {
                "canUpdate": False,
                "message": "Git is not installed or is not on PATH.",
                "repoRoot": str(repo_root),
                "remote": "",
                "branch": "",
                "commit": "",
            }

        branch = self._run_git(["branch", "--show-current"], repo_root=repo_root)
        remote = self._run_git(["remote", "get-url", "origin"], repo_root=repo_root)
        commit = self._run_git(["rev-parse", "--short", "HEAD"], repo_root=repo_root)

        branch_text = branch["stdout"].strip() if branch["ok"] else ""
        remote_text = remote["stdout"].strip() if remote["ok"] else ""
        commit_text = commit["stdout"].strip() if commit["ok"] else ""

        if not remote_text:
            return {
                "canUpdate": False,
                "message": "No GitHub origin remote is configured for this checkout.",
                "repoRoot": str(repo_root),
                "remote": "",
                "branch": branch_text,
                "commit": commit_text,
            }

        return {
            "canUpdate": True,
            "message": "Updates are available through git pull.",
            "repoRoot": str(repo_root),
            "remote": remote_text,
            "branch": branch_text,
            "commit": commit_text,
        }

    def _run_git(
        self,
        args: list[str],
        *,
        repo_root: Path | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        root = repo_root or self._find_repo_root(APP_DIR)
        if root is None:
            return {"ok": False, "error": "No Git checkout was found.", "stdout": "", "stderr": ""}

        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": self._clean_error(str(exc)),
                "stdout": "",
                "stderr": "",
            }

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        if result.returncode != 0:
            return {
                "ok": False,
                "error": self._clean_error((stderr or stdout).strip()),
                "stdout": stdout,
                "stderr": stderr,
            }

        return {"ok": True, "stdout": stdout, "stderr": stderr}

    @staticmethod
    def _find_repo_root(start: Path) -> Path | None:
        for path in [start, *start.parents]:
            if (path / ".git").exists():
                return path
        return None

    def _read_history(self) -> list[dict[str, str]]:
        try:
            if not self._history_file.exists():
                return []
            data = json.loads(self._history_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        if not isinstance(data, list):
            return []

        history: list[dict[str, str]] = []
        for item in data[:HISTORY_LIMIT]:
            if not isinstance(item, dict):
                continue
            history.append(self._clean_history_item(item))
        return history

    def _write_history(self, history: list[dict[str, str]]) -> None:
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        self._history_file.write_text(
            json.dumps(history[:HISTORY_LIMIT], indent=2),
            encoding="utf-8",
        )

    def _set_running(
        self,
        message: str,
        *,
        percent: float | int,
        speed: str = "",
        eta: str = "",
        file: str = "",
        path: str = "",
    ) -> None:
        self._set_progress(
            state="running",
            message=message,
            percent=percent,
            speed=speed,
            eta=eta,
            file=file,
            path=path,
            errorField="",
            rawError="",
        )

    def _set_done(self, final_file: dict[str, str]) -> None:
        self._set_progress(
            state="done",
            message="Download finished",
            percent=100,
            speed="",
            eta="",
            file=final_file.get("file", ""),
            path=final_file.get("path", ""),
            errorField="",
            rawError="",
        )

    def _set_cancelled(self) -> None:
        current_status = self.get_status()
        self._set_progress(
            state="cancelled",
            message="Download cancelled",
            percent=current_status.get("percent", 0),
            speed="",
            eta="",
            file=current_status.get("file", ""),
            path=current_status.get("path", ""),
            errorField="",
            rawError="",
        )

    def _set_error(self, raw_error: str) -> None:
        is_url_error = self._is_url_error(raw_error)
        current_status = self.get_status()
        self._set_progress(
            state="error",
            message=(
                "This YouTube link could not be reached."
                if is_url_error
                else self._clean_error(raw_error)
            ),
            percent=0 if is_url_error else current_status.get("percent", 0),
            speed="",
            eta="",
            file="" if is_url_error else current_status.get("file", ""),
            path="" if is_url_error else current_status.get("path", ""),
            errorField="url" if is_url_error else "",
            rawError=raw_error[:2000],
        )

    def _is_cancel_requested(self) -> bool:
        with self._lock:
            return self._cancel_event.is_set() if self._cancel_event else False

    @staticmethod
    def _clean_history_item(item: dict[str, Any]) -> dict[str, str]:
        return {
            "file": str(item.get("file") or "Download finished")[:260],
            "format": str(item.get("format") or "")[:12],
            "quality": str(item.get("quality") or "")[:40],
            "time": str(item.get("time") or "")[:40],
            "path": str(item.get("path") or "")[:520],
            "url": str(item.get("url") or "")[:520],
        }

    @staticmethod
    def _clean_config(config: dict[str, Any]) -> dict[str, Any]:
        media_type = str(config.get("format") or DEFAULT_CONFIG["format"]).lower()
        quality = str(config.get("quality") or DEFAULT_CONFIG["quality"]).lower()
        mp3_bitrate = DownloaderApi._clean_mp3_bitrate(config.get("mp3Bitrate"))

        return {
            "downloadFolder": str(config.get("downloadFolder") or DOWNLOAD_DIR),
            "format": media_type if media_type in {"mp3", "mp4"} else "mp4",
            "quality": quality if quality in {"720", "1080", "best"} else "1080",
            "mp3Bitrate": mp3_bitrate,
            "subtitles": bool(config.get("subtitles")),
            "saveThumbnail": bool(config.get("saveThumbnail")),
            "embedThumbnail": bool(config.get("embedThumbnail")),
            "embedMetadata": bool(config.get("embedMetadata", True)),
            "autoUpdateApp": bool(config.get("autoUpdateApp")),
        }

    @staticmethod
    def _clean_mp3_bitrate(value: Any) -> str:
        bitrate = str(value or "320")
        return bitrate if bitrate in {"128", "192", "256", "320"} else "320"

    @staticmethod
    def _clean_info(info: dict[str, Any] | None) -> dict[str, Any]:
        if not info:
            return {}

        heights = sorted(
            {
                item.get("height")
                for item in info.get("formats", [])
                if isinstance(item, dict) and isinstance(item.get("height"), int)
            }
        )
        return {
            "title": str(info.get("title") or "Untitled")[:260],
            "channel": str(info.get("channel") or info.get("uploader") or "")[:160],
            "duration": info.get("duration") or 0,
            "thumbnail": str(info.get("thumbnail") or ""),
            "webpageUrl": str(info.get("webpage_url") or ""),
            "viewCount": info.get("view_count") or 0,
            "qualities": [f"{height}p" for height in heights[-8:]],
        }

    @staticmethod
    def _format_bytes(value: float | int | None) -> str:
        if not value:
            return ""

        size = float(value)
        units = ["B", "KB", "MB", "GB"]
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    @staticmethod
    def _format_eta(value: int | None) -> str:
        if not value:
            return ""
        minutes, seconds = divmod(int(value), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:d}:{seconds:02d}"

    @classmethod
    def _format_speed(cls, value: float | int | None) -> str:
        return f"{cls._format_bytes(value)}/s" if value else ""

    @staticmethod
    def _clean_error(message: str) -> str:
        message = message.replace("\n", " ").strip()
        if "ffmpeg" in message.lower():
            return "FFmpeg is required for this format. Install FFmpeg and add it to PATH."
        return message[:260] or "Download failed."

    @staticmethod
    def _is_url_error(message: str) -> bool:
        lowered = message.lower()
        return any(marker in lowered for marker in URL_ERROR_MARKERS)


def main() -> None:
    api = DownloaderApi()
    html_path = UI_DIR / "index.html"
    window = webview.create_window(
        "YT Downloader",
        url=html_path.as_uri(),
        js_api=api,
        width=980,
        height=680,
        min_size=(760, 540),
    )
    api.set_window(window)
    webview.start(debug=False)


if __name__ == "__main__":
    os.environ.setdefault("PYWEBVIEW_GUI", "edgechromium")
    main()
