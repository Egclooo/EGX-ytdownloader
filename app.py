from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

import webview
from yt_dlp import YoutubeDL


IS_FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
UI_DIR = RESOURCE_DIR / "ui"
DOWNLOAD_DIR = APP_DIR / "downloads"
HISTORY_FILE = APP_DIR / "history.json"
HISTORY_LIMIT = 20
INITIAL_PROGRESS: dict[str, Any] = {
    "state": "idle",
    "message": "Ready",
    "percent": 0,
    "speed": "",
    "eta": "",
    "file": "",
    "errorField": "",
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


class DownloaderApi:
    def __init__(self) -> None:
        self._output_dir = DOWNLOAD_DIR
        self._output_dir.mkdir(exist_ok=True)
        self._history_file = HISTORY_FILE
        self._progress = dict(INITIAL_PROGRESS)
        self._lock = threading.Lock()
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
        return {"ok": True, "folder": str(self._output_dir)}

    def get_config(self) -> dict[str, Any]:
        return {
            "downloadFolder": str(self._output_dir),
            "historyFile": str(self._history_file),
            "ffmpegAvailable": shutil.which("ffmpeg") is not None,
        }

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

    def start_download(self, url: str, media_type: str, quality: str) -> dict[str, Any]:
        url = (url or "").strip()
        media_type = (media_type or "mp4").lower()
        quality = (quality or "1080").lower()

        if not YOUTUBE_URL_RE.match(url):
            return {
                "ok": False,
                "error": "Enter a valid YouTube URL.",
                "errorField": "url",
            }

        if media_type not in {"mp3", "mp4"}:
            return {"ok": False, "error": "Choose MP3 or MP4."}

        if self.get_status()["state"] == "running":
            return {"ok": False, "error": "A download is already running."}

        thread = threading.Thread(
            target=self._download_worker,
            args=(url, media_type, quality),
            daemon=True,
        )
        thread.start()
        return {"ok": True}

    def _set_progress(self, **updates: Any) -> None:
        with self._lock:
            self._progress.update(updates)

    def _download_worker(self, url: str, media_type: str, quality: str) -> None:
        self._set_running("Preparing download...", percent=0)

        try:
            with YoutubeDL(self._build_options(media_type, quality)) as ydl:
                info = ydl.extract_info(url, download=True)
                file_name = self._final_filename(ydl, info)
            self._set_done(file_name)
        except Exception as exc:
            self._set_error(str(exc))

    def _build_options(self, media_type: str, quality: str) -> dict[str, Any]:
        output_template = str(self._output_dir / "%(title).180B [%(id)s].%(ext)s")

        base_options: dict[str, Any] = {
            "outtmpl": output_template,
            "progress_hooks": [self._progress_hook],
            "noplaylist": True,
            "windowsfilenames": True,
            "restrictfilenames": False,
            "quiet": True,
            "no_warnings": True,
        }

        if media_type == "mp3":
            return {
                **base_options,
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "320",
                    }
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
        }

    def _progress_hook(self, data: dict[str, Any]) -> None:
        status = data.get("status")

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
            )
            return

        if status == "finished":
            self._set_running(
                "Processing file...",
                percent=100,
                file=Path(data.get("filename") or "").name,
            )

    def _final_filename(self, ydl: YoutubeDL, info: dict[str, Any] | None) -> str:
        if not info:
            return ""

        try:
            path = ydl.prepare_filename(info)
        except Exception:
            return ""

        source_path = Path(path)
        candidates = list(self._output_dir.glob(f"{source_path.stem}.*"))
        if candidates:
            newest = max(candidates, key=lambda item: item.stat().st_mtime)
            return newest.name
        return source_path.name

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
    ) -> None:
        self._set_progress(
            state="running",
            message=message,
            percent=percent,
            speed=speed,
            eta=eta,
            file=file,
            errorField="",
        )

    def _set_done(self, file_name: str) -> None:
        self._set_progress(
            state="done",
            message="Download finished",
            percent=100,
            speed="",
            eta="",
            file=file_name,
            errorField="",
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
            errorField="url" if is_url_error else "",
        )

    @staticmethod
    def _clean_history_item(item: dict[str, Any]) -> dict[str, str]:
        return {
            "file": str(item.get("file") or "Download finished")[:260],
            "format": str(item.get("format") or "")[:12],
            "quality": str(item.get("quality") or "")[:40],
            "time": str(item.get("time") or "")[:40],
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
