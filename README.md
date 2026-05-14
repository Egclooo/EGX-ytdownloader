# YouTube Downloader Webview

A small local Python app with a native webview UI for downloading videos as MP4 or extracting audio as MP3.

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
