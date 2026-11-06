
#!/usr/bin/env bash
set -Eeuo pipefail

: "${BOT_TOKEN:?Missing BOT_TOKEN}"
: "${TELEGRAM_API_ID:?Missing TELEGRAM_API_ID}"
: "${TELEGRAM_API_HASH:?Missing TELEGRAM_API_HASH}"
: "${ADMIN_IDS:?Missing ADMIN_IDS}"

mkdir -p /var/data/bot-api /tmp/megayt

telegram-bot-api \
    --api-id="$TELEGRAM_API_ID" \
    --api-hash="$TELEGRAM_API_HASH" \
    --local \
    --http-port=8081 \
    --dir=/var/data/bot-api &

API_PID=$!

cleanup() {
    kill "$API_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "Starting Telegram Bot API..."

for i in $(seq 1 60); do
    if ! kill -0 "$API_PID" 2>/dev/null; then
        echo "Telegram API server exited."
        exit 1
    fi

    if curl -fsS http://127.0.0.1:8081/ >/dev/null; then
        break
    fi

    sleep 2
done

kill -0 "$API_PID" || exit 1

echo "Telegram API ready."
echo "Starting MegaYT Pro..."

exec python3 bot.py
