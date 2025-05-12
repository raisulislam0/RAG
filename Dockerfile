# syntax=docker/dockerfile:1

FROM python:3.11-slim AS base

WORKDIR /app

FROM base AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*


RUN python -m venv /app/.venv

COPY --link requirements.txt ./

RUN --mount=type=cache,target=/root/.cache/pip \
    .venv/bin/pip install --upgrade pip && \
    .venv/bin/pip install --no-warn-script-location -r requirements.txt

COPY --link . .

FROM base AS final

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    ca-certificates \
    redis-server \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://ollama.com/install.sh | sh

COPY --from=builder /app /app
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN playwright install chromium
RUN playwright install-deps

EXPOSE 8501 11434 6379

RUN echo '#!/bin/bash\n\
# Start Redis server in the background\n\
redis-server --daemonize yes\n\
# Start Ollama in the background\n\
ollama serve &\n\
# Wait for Ollama to start\n\
sleep 5\n\
# Pull the models\n\
ollama pull llama3.2\n\
ollama pull all-minilm\n\
# Start sitemap.py in the background\n\
python sitemap.py &\n\
# Start langchain-emb.py in the background\n\
python embedder.py &\n\
# Start Streamlit\n\
streamlit run streamlit_app.py --server.port=8501 --server.address=0.0.0.0\n\
' > /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"]
