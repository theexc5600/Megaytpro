
#!/usr/bin/env bash
set -Eeuo pipefail

: "${BOT_TOKEN:?Missing BOT_TOKEN}"
: "${TELEGRAM_API_ID:?Missing TELEGRAM_API_ID}"
: "${TELEGRAM_API_HASH:?Missing TELEGRAM_API_HASH}"
: "${ADMIN_IDS:?Missing ADMIN_IDS}"

DATA_DIR="/var/data/bot-api"
MARKER="/var/data/.cloud-logout-done"

mkdir -p "$DATA_DIR" /tmp/megayt

# Perform Telegram cloud API migration only once.
if [[ ! -f "$MARKER" ]]; then
    echo "Performing one-time Telegram API migration..."

    RESPONSE=$(curl -fsS \
        --max-time 30 \
        -X POST \
        "https://api.telegram.org/bot${BOT_TOKEN}/logOut")

    if ! grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' <<< "$RESPONSE"; then
        echo "Telegram migration failed."
        exit 1
    fi

    touch "$MARKER"
    echo "Telegram migration completed."
fi

API_PID=""
BOT_PID=""

cleanup() {
    trap - EXIT INT TERM

    if [[ -n "$BOT_PID" ]]; then
        kill -TERM "$BOT_PID" 2>/dev/null || true
        wait "$BOT_PID" 2>/dev/null || true
    fi

    if [[ -n "$API_PID" ]]; then
        kill -TERM "$API_PID" 2>/dev/null || true
        wait "$API_PID" 2>/dev/null || true
    fi
}

trap cleanup EXIT INT TERM

telegram-bot-api \
    --api-id="$TELEGRAM_API_ID" \
    --api-hash="$TELEGRAM_API_HASH" \
    --local \
    --http-port=8081 \
    --dir="$DATA_DIR" &

API_PID=$!

echo "Waiting for local Telegram API..."

READY=0

for i in $(seq 1 60); do
    if ! kill -0 "$API_PID" 2>/dev/null; then
        echo "Telegram API stopped unexpectedly."
        exit 1
    fi

    if curl -fsS \
        "http://127.0.0.1:8081/bot${BOT_TOKEN}/getMe" \
        | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then
        READY=1
        break
    fi

    sleep 2
done

if [[ "$READY" -ne 1 ]]; then
    echo "Telegram API startup timed out."
    exit 1
fi

echo "Telegram API ready."
echo "Starting MegaYT Pro..."

python3 bot.py &
BOT_PID=$!

wait "$BOT_PID"
