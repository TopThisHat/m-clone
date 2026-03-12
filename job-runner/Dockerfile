FROM python:3.12-slim
WORKDIR /app

# Reuse backend worker utilities (no code duplication)
COPY backend/worker/research.py ./backend/worker/research.py
COPY backend/worker/llm.py ./backend/worker/llm.py
COPY backend/worker/entity_extraction.py ./backend/worker/entity_extraction.py
COPY backend/app/ ./backend/app/

COPY job-runner/pyproject.toml ./
RUN pip install uv && uv pip install --system -e . && \
    uv pip install --system asyncpg openai pydantic-settings python-dotenv \
        pydantic-ai anthropic tavily-python httpx Wikipedia-API yfinance rank-bm25

COPY job-runner/job_runner/ ./job_runner/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/backend

CMD ["python", "-m", "job_runner.main"]
