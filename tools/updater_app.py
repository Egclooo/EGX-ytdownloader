from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import webview


APP_DIR = Path(__file__).resolve().parent
UI_DIR = APP_DIR / "updater_ui"


class UpdaterApi:
    def __init__(self, repo_root: Path, result_file: Path) -> None:
        self.repo_root = repo_root
        self.result_file = result_file
        self._status: dict[str, Any] = {
            "state": "idle",
            "message": "Ready to check for updates.",
            "detail": "",
            "percent": 0,
            "updated": False,
            "done": False,
        }
        self._lock = threading.Lock()
        self._started = False
        self._window: webview.Window | None = None

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def start(self) -> dict[str, Any]:
        if self._started:
            return {"ok": True}
        self._started = True
        threading.Thread(target=self._run_update, daemon=True).start()
        return {"ok": True}

    def close(self) -> dict[str, Any]:
        if self._window is not None:
            self._window.destroy()
        return {"ok": True}

    def _set_status(self, **updates: Any) -> None:
        with self._lock:
            self._status.update(updates)

    def _run_update(self) -> None:
        try:
            self._set_status(
                state="running",
                message="Checking repository...",
                detail=str(self.repo_root),
                percent=8,
            )
            if not (self.repo_root / ".git").exists():
                self._finish("skipped", "This folder is not a Git checkout.", 100)
                return

            self._set_status(
                message="Fetching GitHub updates...",
                detail="git fetch --quiet --prune origin",
                percent=25,
            )
            self._git("fetch", "--quiet", "--prune", "origin")

            self._set_status(message="Reading current branch...", detail="", percent=42)
            branch = self._git("branch", "--show-current").strip()
            if not branch:
                raise RuntimeError("Could not detect the current Git branch.")

            self._set_status(message="Comparing local and remote commits...", detail=branch, percent=58)
            local = self._git("rev-parse", "HEAD").strip()
            remote = self._git("rev-parse", f"origin/{branch}").strip()
            if local == remote:
                self._finish("done", "Already up to date.", 100)
                return

            self._set_status(
                message="Pulling latest files...",
                detail=f"git pull --ff-only --autostash origin {branch}",
                percent=76,
            )
            output = self._git("pull", "--ff-only", "--autostash", "origin", branch)
            self.result_file.write_text("updated", encoding="ascii")
            self._finish(
                "updated",
                "Update complete. Restarting launcher...",
                100,
                detail=output.strip()[-1200:],
                updated=True,
            )
        except Exception as exc:
            self._finish("error", "Update failed.", 100, detail=str(exc))

    def _finish(
        self,
        state: str,
        message: str,
        percent: int,
        *,
        detail: str = "",
        updated: bool = False,
    ) -> None:
        self._set_status(
            state=state,
            message=message,
            detail=detail,
            percent=percent,
            updated=updated,
            done=True,
        )
        if state in {"done", "updated", "skipped"}:
            threading.Thread(target=self._close_after_delay, daemon=True).start()

    def _close_after_delay(self) -> None:
        time.sleep(2.2)
        if self._window is not None:
            self._window.destroy()

    def _git(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo_root), *args],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        if result.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed with exit code {result.returncode}.\n{output}"
            )
        return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--result-file", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api = UpdaterApi(Path(args.repo_root).resolve(), Path(args.result_file).resolve())
    window = webview.create_window(
        "YT Downloader Updater",
        url=(UI_DIR / "index.html").as_uri(),
        js_api=api,
        width=560,
        height=390,
        min_size=(500, 340),
    )
    api.set_window(window)
    webview.start(debug=False)


if __name__ == "__main__":
    os.environ.setdefault("PYWEBVIEW_GUI", "edgechromium")
    sys.exit(main())
