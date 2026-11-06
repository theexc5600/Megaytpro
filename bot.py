
import asyncio
import logging
import os
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, FSInputFile
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from config import (
    BOT_TOKEN,
    BOT_API_BASE,
    ADMIN_IDS,
    INITIAL_ALLOWED_IDS,
    AUTH_FILE,
    REVOKED_FILE,
    DOWNLOAD_DIR,
    MAX_UPLOAD_BYTES,
    MAX_CONCURRENT_DOWNLOADS,
)

from downloader import (
    validate_url,
    download_media,
    QUALITIES,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

log = logging.getLogger("MegaYTPro")

# Telegram API connection
api = TelegramAPIServer.from_base(
    BOT_API_BASE,
    is_local=True,
)

session = AiohttpSession(api=api)
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()

# User access and job tracking
allowed_users = set(ADMIN_IDS) | set(INITIAL_ALLOWED_IDS)
revoked_users = set()

download_tasks = {}
download_processes = {}
active_users = set()

slots = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
auth_lock = asyncio.Lock()


def read_ids(filename):
    try:
        return {
            int(line.strip())
            for line in Path(filename).read_text().splitlines()
            if line.strip().isdigit()
        }
    except FileNotFoundError:
        return set()


def save_ids(filename, values):
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".tmp")

    temporary.write_text(
        "".join(f"{user_id}\n" for user_id in sorted(values))
    )

    os.replace(temporary, path)


def load_authorized_users():
    global allowed_users, revoked_users

    allowed_users |= read_ids(AUTH_FILE)
    revoked_users = read_ids(REVOKED_FILE)

    # Revocations always take precedence over initial access.
    allowed_users.difference_update(revoked_users)
    allowed_users.update(ADMIN_IDS)

    log.info("Loaded %s authorized users", len(allowed_users))


def save_access():
    save_ids(AUTH_FILE, allowed_users - ADMIN_IDS)
    save_ids(REVOKED_FILE, revoked_users)


def is_admin(user_id):
    return user_id in ADMIN_IDS


def is_authorized(user_id):
    return (
        user_id in allowed_users
        and user_id not in revoked_users
    )


async def authorize(message: Message):
    if not message.from_user:
        return False

    if message.chat.type != "private":
        await message.answer(
            "Please use MegaYT Pro in a private chat."
        )
        return False

    user_id = message.from_user.id

    if is_authorized(user_id):
        return True

    await message.answer(
        "🔒 Private bot.\n"
        "You are not authorized to use MegaYT Pro.\n"
        f"Your Telegram ID: {user_id}"
    )
    return False


async def admin_only(message: Message):
    if not message.from_user:
        return False

    if not is_admin(message.from_user.id):
        await message.answer("⛔ Administrator access required.")
        return False

    return True


async def stop_process(proc):
    if proc is None or proc.returncode is not None:
        return

    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    except ProcessLookupError:
        pass


async def send_help(message: Message):
    await message.answer(
        "🚀 MegaYT Pro v3.1\n\n"
        "/video URL [quality] - Download video\n"
        "/audio URL - Download MP3\n"
        "/cancel - Cancel your download\n"
        "/status - Bot status\n"
        "/help - Show commands\n"
        "/about - About the bot\n\n"
        "Quality options:\n"
        "360p, 480p, 720p, 1080p, 1440p, 2160p\n\n"
        "Individual YouTube videos only.\n"
        "Playlists are disabled."
    )


async def process_download(
    message: Message,
    url: str,
    audio=False,
    quality=2160,
):
    user_id = message.from_user.id

    if not is_authorized(user_id):
        await authorize(message)
        return

    if not validate_url(url):
        await message.answer("❌ Invalid YouTube video URL.")
        return

    if not audio and quality not in QUALITIES:
        await message.answer("❌ Unsupported video quality.")
        return

    if user_id in active_users:
        await message.answer(
            "⚠️ You already have an active download."
        )
        return

    active_users.add(user_id)
    current_task = asyncio.current_task()
    download_tasks[user_id] = current_task

    status = None
    media = None

    try:
        async with slots:
            if not is_authorized(user_id):
                raise PermissionError("Access was revoked.")

            status = await message.answer(
                "⏳ Preparing your download..."
            )

            with tempfile.TemporaryDirectory(
                prefix="megayt_",
                dir=DOWNLOAD_DIR,
            ) as folder:

                def register_process(proc):
                    download_processes[user_id] = proc

                await status.edit_text(
                    "⬇️ Downloading...\n"
                    f"Quality: {'MP3' if audio else str(quality) + 'p'}"
                )

                media = await download_media(
                    url=url,
                    folder=folder,
                    audio=audio,
                    quality=quality,
                    on_process=register_process,
                )

                download_processes.pop(user_id, None)

                if not is_authorized(user_id):
                    raise PermissionError("Access was revoked.")

                if not media.exists():
                    raise RuntimeError("Downloaded file is missing.")

                size = media.stat().st_size

                if size <= 0 or size > MAX_UPLOAD_BYTES:
                    raise RuntimeError(
                        "File is empty or exceeds the upload limit."
                    )

                await status.edit_text(
                    "📤 Uploading your media to Telegram..."
                )

                if not is_authorized(user_id):
                    raise PermissionError("Access was revoked.")

                await message.answer_document(
                    FSInputFile(media, filename=media.name),
                    caption=(
                        "✅ Download completed!\n\n"
                        f"📁 {media.name}\n"
                        f"📦 {size / (1024 ** 2):.1f} MB"
                    ),
                )

                await status.edit_text(
                    "✅ Your media was delivered successfully."
                )

    except asyncio.CancelledError:
        await stop_process(download_processes.get(user_id))

        if status:
            try:
                await status.edit_text(
                    "🚫 Download cancelled."
                )
            except Exception:
                pass

    except PermissionError:
        await stop_process(download_processes.get(user_id))

        if status:
            try:
                await status.edit_text(
                    "🔒 Your access is no longer authorized."
                )
            except Exception:
                pass

    except Exception:
        log.exception("Download failed for user %s", user_id)

        if status:
            try:
                await status.edit_text(
                    "❌ Download failed.\n"
                    "Check the URL, quality, available storage "
                    "or Telegram upload connection."
                )
            except Exception:
                pass
        else:
            await message.answer("❌ Download failed.")

    finally:
        download_processes.pop(user_id, None)
        active_users.discard(user_id)

        if download_tasks.get(user_id) is current_task:
            download_tasks.pop(user_id, None)


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
            "MegaYT Pro v3.1\n"
            "Private YouTube media downloader."
        )


@dp.message(Command("status"))
async def status_command(message: Message):
    if not await authorize(message):
        return

    await message.answer(
        "🟢 MegaYT Pro is online.\n"
        f"Active downloads: {len(active_users)}\n"
        f"Maximum concurrent downloads: "
        f"{MAX_CONCURRENT_DOWNLOADS}"
    )


@dp.message(Command("video"))
async def video_command(message: Message):
    if not await authorize(message):
        return

    parts = (message.text or "").split()

    if len(parts) not in (2, 3):
        await message.answer(
            "Usage:\n/video YOUTUBE_URL [quality]\n\n"
            "Example:\n/video https://youtu.be/VIDEO_ID 1080"
        )
        return

    try:
        quality = int(parts[2]) if len(parts) == 3 else 2160
    except ValueError:
        await message.answer("Quality must be a number.")
        return

    await process_download(
        message,
        parts[1],
        quality=quality,
    )


@dp.message(Command("audio"))
async def audio_command(message: Message):
    if not await authorize(message):
        return

    parts = (message.text or "").split(maxsplit=1)

    if len(parts) != 2:
        await message.answer(
            "Usage:\n/audio YOUTUBE_URL"
        )
        return

    await process_download(
        message,
        parts[1].strip(),
        audio=True,
    )


@dp.message(Command("cancel"))
async def cancel_command(message: Message):
    if not await authorize(message):
        return

    user_id = message.from_user.id
    task = download_tasks.get(user_id)

    if task is None or task.done():
        await message.answer("No active download to cancel.")
        return

    task.cancel()

    await message.answer("🚫 Cancellation requested.")


@dp.message(Command("allow"))
async def allow_command(message: Message):
    if not await admin_only(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "Usage: /allow TELEGRAM_USER_ID"
        )
        return

    target = int(parts[1])

    async with auth_lock:
        revoked_users.discard(target)
        allowed_users.add(target)
        save_access()

    await message.answer(
        f"✅ User {target} is now authorized."
    )


@dp.message(Command("revoke"))
async def revoke_command(message: Message):
    if not await admin_only(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "Usage: /revoke TELEGRAM_USER_ID"
        )
        return

    target = int(parts[1])

    if target in ADMIN_IDS:
        await message.answer(
            "❌ Administrator accounts cannot be revoked."
        )
        return

    async with auth_lock:
        allowed_users.discard(target)
        revoked_users.add(target)
        save_access()

    task = download_tasks.get(target)

    if task and not task.done():
        task.cancel()

    await message.answer(
        f"✅ Access revoked for user {target}."
    )


@dp.message(Command("users"))
async def users_command(message: Message):
    if not await admin_only(message):
        return

    users = sorted(allowed_users - revoked_users)

    text = (
        "👥 Authorized users:\n"
        + "\n".join(str(user) for user in users)
        if users else "No authorized users."
    )

    await message.answer(text)


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
        await message.answer(
            "Send an individual YouTube video URL "
            "or use /help."
        )


async def main():
    Path(DOWNLOAD_DIR).mkdir(
        parents=True,
        exist_ok=True,
    )

    Path(AUTH_FILE).parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    load_authorized_users()

    log.info("MegaYT Pro v3.1 starting")
    log.info("Authorized users: %s", len(allowed_users))

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        for proc in list(download_processes.values()):
            await stop_process(proc)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
    
