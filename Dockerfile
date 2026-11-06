FROM ubuntu:24.04 AS api-builder

RUN apt-get update && apt-get install -y \
    git cmake g++ make gperf \
    zlib1g-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --recursive \
    https://github.com/tdlib/telegram-bot-api.git /src

WORKDIR /src

RUN cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --target install -j2


FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    python3 python3-venv \
    ffmpeg curl ca-certificates \
    libssl3 zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=api-builder \
    /usr/local/bin/telegram-bot-api \
    /usr/local/bin/telegram-bot-api

WORKDIR /app

COPY requirements.txt .

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

COPY . .

RUN chmod +x start.sh

CMD ["./start.sh"]

