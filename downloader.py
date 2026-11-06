
import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from config import MAX_UPLOAD_BYTES

QUALITIES = {360, 480, 720, 1080, 1440, 2160}


def validate_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()

        if parsed.scheme != "https":
            return False

        if host == "youtu.be":
            return bool(parsed.path.strip("/"))

        if host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
            if parsed.path == "/watch":
                return bool(parse_qs(parsed.query).get("v"))

            if parsed.path.startswith(("/shorts/", "/live/")):
                return len(parsed.path.split("/")) >= 3

        return False

    except Exception:
        return False


def safe_title(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]', "_", value)
    return value[:120].strip() or "youtube_media"


async def download_media(
    url: str,
    folder: str,
    audio: bool = False,
    quality: int = 2160,
    on_process=None
):
    if quality not in QUALITIES:
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

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    if on_process:
        on_process(process)

    stderr = []

    while True:
        line = await process.stderr.readline()

        if not line:
            break

        decoded = line.decode(errors="replace").strip()

        if decoded:
            stderr.append(decoded)
            stderr = stderr[-20:]

    return_code = await process.wait()

    if return_code != 0:
        raise RuntimeError(
            "\n".join(stderr[-8:]) or "Download process failed."
        )

    files = [
        p for p in Path(folder).iterdir()
        if p.is_file()
        and p.suffix.lower() in {
            ".mp4", ".mkv", ".webm", ".mp3", ".m4a"
        }
    ]

    if not files:
        raise RuntimeError("No output media file was created.")

    media = max(files, key=lambda p: p.stat().st_mtime)

    if media.stat().st_size > MAX_UPLOAD_BYTES:
        raise RuntimeError("Media exceeds the configured upload limit.")

    return media
  
