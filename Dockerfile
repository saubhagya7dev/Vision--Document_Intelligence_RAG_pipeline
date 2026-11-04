# Linux CPU build recipe; runtime validation requires Docker (see Phase 7 guide).
FROM python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy HF_HOME=/home/vision/.cache/huggingface
WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.7
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable && useradd --create-home --uid 10001 vision \
    && mkdir /library && chown vision:vision /library
USER vision
ENV DATA_DIR=/library EMBEDDING_DEVICE=cpu BIND_HOST=127.0.0.1
HEALTHCHECK --interval=30s --timeout=5s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)"]
CMD ["/app/.venv/bin/python", "-m", "vision_rag.api.main"]
