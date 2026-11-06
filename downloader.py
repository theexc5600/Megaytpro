
import asyncio
import os
import signal
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from config import MAX_UPLOAD_BYTES

QUALITIES = {360, 480, 720, 1080, 1440, 2160}

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov"
}


def validate_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()

        if parsed.scheme != "https":
            return False

        if host == "youtu.be":
            return bool(parsed.path.strip("/"))

        valid_hosts = {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
        }

        if host not in valid_hosts:
            return False

        if parsed.path == "/watch":
            return bool(parse_qs(parsed.query).get("v"))

        if parsed.path.startswith(("/shorts/", "/live/")):
            return len(parsed.path.split("/")) >= 3

        return False

    except Exception:
        return False


async def stop_process_group(proc):
    if proc.returncode is not None:
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        await asyncio.wait_for(
            proc.wait(),
            timeout=5,
        )
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        await proc.wait()


async def download_media(
    url: str,
    folder: str,
    audio: bool = False,
    quality: int = 2160,
    on_process=None,
):
    if not validate_url(url):
        raise ValueError("Invalid individual YouTube video URL.")

    if not audio and quality not in QUALITIES:
        raise ValueError("Unsupported video quality.")

    Path(folder).mkdir(parents=True, exist_ok=True)

    output = str(
        Path(folder) / "%(title).120B [%(id)s].%(ext)s"
    )

    command = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--newline",
        "--retries", "3",
        "--fragment-retries", "3",
        "--socket-timeout", "30",
        "--max-filesize", str(MAX_UPLOAD_BYTES),
        "--output", output,
    ]

    if audio:
        command += [
            "--format", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "192K",
        ]
    else:
        command += [
            "--format",
            (
                f"bestvideo[height<={quality}][ext=mp4]"
                "+bestaudio[ext=m4a]"
                f"/best[height<={quality}][ext=mp4]"
                f"/best[height<={quality}]"
            ),
            "--merge-output-format", "mp4",
        ]

    command.append(url)

    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    if on_process:
        on_process(proc)

    communication = asyncio.create_task(proc.communicate())

    try:
        _, stderr = await communication

    except asyncio.CancelledError:
        cleanup = asyncio.create_task(
            stop_process_group(proc)
        )

        try:
            await asyncio.shield(cleanup)
        finally:
            if not communication.done():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(communication),
                        timeout=5,
                    )
                except asyncio.TimeoutError:
                    pass

        raise

    if proc.returncode != 0:
        error = stderr.decode(
            errors="replace"
        )[-2500:]

        raise RuntimeError(
            error or "YouTube download failed."
        )

    files = [
        p for p in Path(folder).iterdir()
        if p.is_file()
        and p.suffix.lower() in (
            {".mp3", ".m4a", ".opus"}
            if audio else VIDEO_EXTENSIONS
        )
    ]

    if not files:
        raise RuntimeError(
            "Download completed without a valid media file."
        )

    media = max(
        files,
        key=lambda p: p.stat().st_mtime,
    )

    size = media.stat().st_size

    if size <= 0:
        raise RuntimeError("Downloaded file is empty.")

    if size > MAX_UPLOAD_BYTES:
        raise RuntimeError(
            "Downloaded file exceeds the configured upload limit."
        )

    return media
    
