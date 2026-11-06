
import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]

BOT_API_BASE = os.getenv(
    "BOT_API_BASE",
    "http://127.0.0.1:8081"
)

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

INITIAL_ALLOWED_IDS = {
    int(x.strip())
    for x in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if x.strip().isdigit()
}

if not ADMIN_IDS:
    raise RuntimeError(
        "At least one administrator must be configured."
    )

AUTH_FILE = "/var/data/authorized_users.txt"
REVOKED_FILE = "/var/data/revoked_users.txt"

DOWNLOAD_DIR = "/tmp/megayt"

MAX_UPLOAD_BYTES = 1_900_000_000
MAX_CONCURRENT_DOWNLOADS = 2

MAX_QUALITY = 2160
```

Commit message:

```text
Improve configuration and access security
```

Tap **Commit changes**.

## Step 2 — What we'll correct next

| File | Improvement |
|---|---|
| `bot.py` | Persistent authorization and revocation |
| `bot.py` | Better cancellation and job management |
| `downloader.py` | Better process cleanup and file validation |
| `Dockerfile` | Reliable deployment build |
| `start.sh` | Server startup and shutdown handling |

## Current progress

<box border radius="lg" padding={3} gap={2}>
  <row justify=between>
    **GitHub preparation**
    <badge color="success">8 files uploaded</badge>
  </row>
  <row justify=between>
    Configuration correction
    <badge color="warning">In progress</badge>
  </row>
  <row justify=between>
    Code validation
    <badge>Pending</badge>
  </row>
  <row justify=between>
    Render deployment
    <badge>Pending</badge>
  </row>
</box>

**Please tell me once you've updated and committed `config.py`.** Then we'll fix `bot.py`, particularly the private-user authorization system.
