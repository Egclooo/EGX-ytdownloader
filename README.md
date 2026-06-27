# EGX Downloader Webview

A small local Python app with a native webview UI for downloading YouTube, TikTok, or Instagram videos as MP4 or extracting audio as MP3.

Use this only for videos you own, videos with a license that allows downloading, or content where you have permission.

## Setup

```powershell
cd yt_downloader_webview
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

MP3 conversion and high quality MP4 merging require FFmpeg to be installed and available on your `PATH`.

## Run

```powershell
.\.venv\Scripts\python.exe app.py
```

Downloads are saved to the `downloads` folder by default. You can pick another folder in the app.
Download history is saved locally to `history.json`.

## One-Click Windows Start

Run:

```text
start.bat
```

The launcher checks for Python, installs Python 3.12 if needed, creates `.venv`,
installs pip/dependencies, checks GitHub updates in a separate pywebview updater
window, restarts the launcher after a successful update, then starts the app.

GitHub updates require the folder to be a Git checkout and require Git on PATH.
If Python or Git is missing, the launcher tries `winget` first. If `winget` is
not available or fails, it downloads the official installers directly and runs
them silently.

## Build EXE

Put your icon at:

```text
assets/app.ico
```

Then run:

```powershell
.\build_exe.bat
```

The exe is created at:

```text
dist\YT Downloader\YT Downloader.exe
```

Copy the whole `dist\YT Downloader` folder to another Windows machine. The app
does not require Python on that machine.

## Updates

The app includes two update actions:

- `Update yt-dlp` upgrades the Python package when running from source.
- `Update app` runs `git pull --ff-only` against the Git checkout.

Git-pull app updates require the app to be inside a cloned Git repository and
require Git to be installed on the machine. A standalone copied EXE folder does
not contain enough Git metadata to pull updates by itself.

For a public standalone auto-updater, publish versioned builds through GitHub
Releases and download the newer release from the app instead of using `git pull`.
