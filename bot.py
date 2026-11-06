
import asyncio
import logging
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, FSInputFile
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from config import (
    BOT_TOKEN, BOT_API_BASE, ADMIN_IDS,
    INITIAL_ALLOWED_IDS, AUTH_FILE,
    DOWNLOAD_DIR, MAX_UPLOAD_BYTES,
    MAX_CONCURRENT_DOWNLOADS
)
from downloader import validate_url, download_media, QUALITIES

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("MegaYTPro")

api = TelegramAPIServer.from_base(
    BOT_API_BASE,
    is_local=True
)

session = AiohttpSession(api=api)
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()

allowed_users = set(INITIAL_ALLOWED_IDS) | set(ADMIN_IDS)
jobs = {}
cancelled = set()
active_users = set()

slots = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
auth_lock = asyncio.Lock()


def load_authorized_users():
    Path(AUTH_FILE).parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(AUTH_FILE, "r") as f:
            for line in f:
                value = line.strip()
                if value.isdigit():
                    allowed_users.add(int(value))
    except FileNotFoundError:
        pass

    save_authorized_users()


def save_authorized_users():
    Path(AUTH_FILE).parent.mkdir(parents=True, exist_ok=True)
    temporary = AUTH_FILE + ".tmp"

    with open(temporary, "w") as f:
        for user_id in sorted(allowed_users):
            f.write(f"{user_id}\n")

    Path(temporary).replace(AUTH_FILE)


def is_admin(user_id):
    return user_id in ADMIN_IDS


def is_authorized(user_id):
    return user_id in allowed_users


async def authorize(message: Message):
    user_id = message.from_user.id

    if is_authorized(user_id):
        return True

    await message.answer(
        "🔒 Private bot.\n"
        "You are not authorized to use MegaYT Pro.\n"
        f"Your Telegram ID: {user_id}"
    )
    return False


async def send_help(message: Message):
    await message.answer(
        "🚀 MegaYT Pro v3\n\n"
        "/video URL [quality] - Download video\n"
        "/audio URL - Download MP3\n"
        "/cancel - Cancel your download\n"
        "/status - Bot status\n"
        "/help - Help\n"
        "/about - About\n\n"
        "Available qualities: 360, 480, 720, "
        "1080, 1440, 2160.\n"
        "Playlists are disabled."
    )


async def process_download(
    message: Message,
    url: str,
    audio=False,
    quality=2160
):
    user_id = message.from_user.id

    if not await authorize(message):
        return

    if not validate_url(url):
        await message.answer("❌ Invalid YouTube URL.")
        return

    if not audio and quality not in QUALITIES:
        await message.answer(
            "❌ Choose: 360, 480, 720, 1080, 1440 or 2160."
        )
        return

    if user_id in active_users:
        await message.answer(
            "⚠️ You already have an active download."
        )
        return

    active_users.add(user_id)
    status = None

    try:
        async with slots:
            status = await message.answer(
                "⏳ Download starting..."
            )

            with tempfile.TemporaryDirectory(
                prefix="megayt_",
                dir=DOWNLOAD_DIR
            ) as folder:

                def register_process(proc):
                    jobs[user_id] = proc

                await status.edit_text(
                    "⬇️ Downloading media...\n"
                    f"Quality: {'MP3' if audio else str(quality) + 'p'}"
                )

                media = await download_media(
                    url=url,
                    folder=folder,
                    audio=audio,
                    quality=quality,
                    on_process=register_process
                )

                jobs.pop(user_id, None)

                if user_id in cancelled:
                    cancelled.discard(user_id)
                    await status.edit_text("🚫 Download cancelled.")
                    return

                await status.edit_text("📤 Uploading to Telegram...")

                size = media.stat().st_size

                if size > MAX_UPLOAD_BYTES:
                    raise RuntimeError("Upload limit exceeded.")

                await message.answer_document(
                    FSInputFile(media, filename=media.name),
                    caption=(
                        "✅ Download completed!\n\n"
                        f"📁 {media.name}\n"
                        f"📦 {size / (1024 ** 2):.1f} MB"
                    )
                )

                await status.edit_text("✅ Successfully delivered.")

    except Exception:
        log.exception("Download failed")

        text = (
            "🚫 Download cancelled."
            if user_id in cancelled
            else "❌ Download failed. Check the URL, "
                 "availability, quality or file size."
        )

        if status:
            try:
                await status.edit_text(text)
            except Exception:
                pass
        else:
            await message.answer(text)

    finally:
        jobs.pop(user_id, None)
        cancelled.discard(user_id)
        active_users.discard(user_id)


@dp.message(CommandStart())
async def start(message: Message):
    if await authorize(message):
        await send_help(message)


@dp.message(Command("help"))
async def help_command(message: Message):
    if await authorize(message):
        await send_help(message)


@dp.message(Command("about"))
async def about(message: Message):
    if await authorize(message):
        await message.answer(
            "MegaYT Pro v3\nPrivate YouTube downloader."
        )


@dp.message(Command("status"))
async def status_command(message: Message):
    if not await authorize(message):
        return

    await message.answer(
        "🟢 Bot online\n"
        f"Active users: {len(active_users)}\n"
        f"Download limit: {MAX_CONCURRENT_DOWNLOADS}"
    )


@dp.message(Command("video"))
async def video_command(message: Message):
    if not await authorize(message):
        return

    parts = (message.text or "").split()

    if len(parts) not in (2, 3):
        await message.answer(
            "Usage: /video URL [quality]\n"
            "Example: /video https://youtu.be/VIDEO_ID 1080"
        )
        return

    try:
        quality = int(parts[2]) if len(parts) == 3 else 2160
    except ValueError:
        await message.answer("Quality must be a number.")
        return

    await process_download(message, parts[1], quality=quality)


@dp.message(Command("audio"))
async def audio_command(message: Message):
    if not await authorize(message):
        return

    parts = (message.text or "").split(maxsplit=1)

    if len(parts) != 2:
        await message.answer("Usage: /audio YOUTUBE_URL")
        return

    await process_download(message, parts[1].strip(), audio=True)


@dp.message(Command("cancel"))
async def cancel_command(message: Message):
    user_id = message.from_user.id

    if not await authorize(message):
        return

    proc = jobs.get(user_id)

    if not proc or proc.returncode is not None:
        await message.answer("No active download to cancel.")
        return

    cancelled.add(user_id)
    proc.terminate()

    await message.answer("🚫 Cancellation requested.")


@dp.message(Command("allow"))
async def allow_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /allow TELEGRAM_USER_ID")
        return

    target = int(parts[1])

    async with auth_lock:
        allowed_users.add(target)
        save_authorized_users()

    await message.answer(f"✅ Authorized user {target}.")


@dp.message(Command("revoke"))
async def revoke_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /revoke TELEGRAM_USER_ID")
        return

    target = int(parts[1])

    if target in ADMIN_IDS:
        await message.answer("Cannot revoke an administrator.")
        return

    async with auth_lock:
        allowed_users.discard(target)
        save_authorized_users()

    proc = jobs.get(target)

    if proc and proc.returncode is None:
        cancelled.add(target)
        proc.terminate()

    await message.answer(f"✅ Access revoked for {target}.")


@dp.message(Command("users"))
async def users_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "Authorized users:\n"
        + "\n".join(str(x) for x in sorted(allowed_users))
    )


@dp.message()
async def automatic_url(message: Message):
    if not await authorize(message):
        return

    if not message.text:
        return

    url = message.text.strip()

    if validate_url(url):
        await process_download(message, url)
    else:
        await message.answer("Send a YouTube URL or use /help.")


async def main():
    load_authorized_users()
    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

    log.info("MegaYT Pro v3 starting")
    log.info("Authorized users: %s", len(allowed_users))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    
