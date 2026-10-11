"""Single-page Voice Schedule app download site."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse


ROOT = Path(__file__).resolve().parent
APK_OVERRIDE = os.environ.get("APK_PATH")
if APK_OVERRIDE:
    APK_PATH = Path(APK_OVERRIDE).expanduser().resolve()
else:
    APK_CANDIDATES = sorted((ROOT / "bin").glob("voiceschedule-*.apk"), key=lambda path: path.stat().st_mtime)
    APK_PATH = APK_CANDIDATES[-1] if APK_CANDIDATES else ROOT / "bin" / "voiceschedule.apk"

app = FastAPI(title="Voice Schedule", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/", response_class=HTMLResponse)
def home():
    ready = APK_PATH.is_file()
    download = (
        '<a class="button" href="/download">Download the Android app</a>'
        if ready
        else '<span class="button disabled" aria-disabled="true">APK is not available yet</span>'
    )
    apk_note = (
        "The Android installer is ready to download."
        if ready
        else "Build the APK with Buildozer and place it at the configured APK path to enable downloads."
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#10251f">
  <title>Voice Schedule — reminders that speak</title>
  <style>
    :root {{ color-scheme: light; --ink:#10251f; --muted:#53645d; --green:#176b4a; --paper:#f6f8f3; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; background:radial-gradient(ellipse at 80% 5%,#d5eadb,transparent 40%),var(--paper); color:var(--ink); font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }}
    main {{ width:min(780px,calc(100% - 32px)); margin:0 auto; padding:56px 0; }}
    .card {{ background:#ffffffed; border:1px solid #dbe5dc; border-radius:26px; padding:clamp(24px,6vw,54px); box-shadow:0 24px 70px #10251f12; }}
    .eyebrow {{ color:var(--green); font-size:.8rem; font-weight:750; letter-spacing:.14em; text-transform:uppercase; }}
    h1 {{ max-width:620px; margin:.4rem 0 1rem; font-size:clamp(2.2rem,7vw,4rem); letter-spacing:-.055em; line-height:1.05; }}
    .intro {{ max-width:610px; color:var(--muted); font-size:1.1rem; }}
    .button {{ display:inline-block; margin:20px 0 8px; padding:14px 22px; border:0; border-radius:12px; background:var(--green); color:white; font-weight:750; text-decoration:none; }}
    .button:hover {{ background:#10583d; }}
    .disabled {{ background:#79867f; cursor:not-allowed; }}
    .status {{ color:var(--muted); font-size:.9rem; }}
    h2 {{ margin:34px 0 8px; font-size:1.35rem; }}
    ol {{ padding-left:1.3rem; }}
    li {{ padding:.25rem 0 .4rem .25rem; }}
    .note {{ margin-top:26px; padding:16px 18px; border-radius:12px; background:#edf5ee; color:#34483d; font-size:.92rem; }}
    footer {{ padding:22px 4px; color:var(--muted); font-size:.85rem; }}
  </style>
</head>
<body>
  <main>
    <article class="card">
      <div class="eyebrow">A little help staying on track</div>
      <h1>Let your schedule speak for itself.</h1>
      <p class="intro">Voice Schedule gives you spoken reminders for the activities you plan, whether you repeat one routine every day or set a different routine for each weekday.</p>
      {download}
      <div class="status">{apk_note}</div>
      <h2>How to use Voice Schedule</h2>
      <ol>
        <li>Install the APK on your Android phone and open Voice Schedule.</li>
        <li>On first launch, connect to the internet to download the offline voice and speech models.</li>
        <li>Open <strong>Schedule</strong> and choose one schedule for every day or separate schedules for each weekday.</li>
        <li>Add activities with their time in 24-hour format, then return to Home to review them.</li>
        <li>When Android speech and audio support is included, the app speaks the activity at its scheduled time and listens for up to one minute for a simple acknowledgement.</li>
      </ol>
      <div class="note"><strong>Current Android build status:</strong> the app interface and schedule editor are packaged, but the speech and audio libraries still need Android-compatible builds before spoken reminders can run in the APK. Android may also limit reminders when the app is backgrounded; keep the app open until reliable background alarm support is included.</div>
    </article>
    <footer>Voice Schedule · Android APK</footer>
  </main>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/download")
def download_apk():
    if not APK_PATH.is_file():
        raise HTTPException(status_code=404, detail="The APK has not been built or configured on this server.")
    return FileResponse(
        APK_PATH,
        media_type="application/vnd.android.package-archive",
        filename=APK_PATH.name,
    )
