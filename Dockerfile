# ---------------------------------------------------------------------------
# Stage 1: Install dependencies
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency specs first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

# Copy source and package metadata required by pyproject
COPY mcp_crawl4ai/ ./mcp_crawl4ai/
COPY README.md LICENSE ./
RUN uv sync --no-dev --frozen

# Install Playwright browsers (required by crawl4ai)
RUN uv run crawl4ai-setup

# ---------------------------------------------------------------------------
# Stage 2: Runtime image
# ---------------------------------------------------------------------------
FROM python:3.13-slim

# Install uv (required by CMD)
RUN pip install --no-cache-dir uv

# Install Playwright system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app /app
# Playwright browser binaries live in ~/.cache/ms-playwright by default
COPY --from=builder /root/.cache /root/.cache

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "mcp-crawl4ai", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
