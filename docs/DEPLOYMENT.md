# Deployment

This project is prepared for Render's free web-service tier.

## Required Render Settings

Build command:

```bash
pip install -r requirements.txt && python ingest.py
```

Start command:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Health-check path:

```text
/health
```

## Required Environment Variables

Set these in Render's environment-variable UI:

```text
OPENAI_API_KEY
GITHUB_USERNAME
ALLOWED_ORIGINS
```

After the service URL is created, set `ALLOWED_ORIGINS` to the Render URL, for example:

```text
https://your-render-service.onrender.com
```

Optional variables:

```text
GITHUB_TOKEN
MODEL_NAME
EMBEDDING_MODEL
MAX_OUTPUT_TOKENS
OPENAI_TIMEOUT_SECONDS
RAG_TOP_K
RAG_MIN_SCORE
RATE_LIMIT_REQUESTS
RATE_LIMIT_WINDOW_SECONDS
MAX_QUESTION_CHARS
PUSHOVER_USER
PUSHOVER_TOKEN
```

## RAG Source Strategy

Private PDFs and local vector indexes are excluded from Git.

For the first Render deployment, the safe strategy is:

1. Commit code, static assets, docs, and `summary.txt`.
2. Exclude private files under `documents/`.
3. Exclude `vector_store/`.
4. Let Render run `python ingest.py` during build.
5. Use `GITHUB_USERNAME` to ingest approved public GitHub profile/repository metadata.

If richer resume/LinkedIn grounding is needed in production, add only reviewed public-safe source files or move private source files to a secure storage workflow that is not committed to Git.

## Ephemeral Filesystem Note

Render's runtime filesystem is ephemeral. A file created at runtime should not be treated as permanent. This project builds the index during deployment so it is part of the deployed build artifact. For larger production use, move the index to durable external storage.

## Pre-Deployment Checklist

- `.env` is not tracked.
- `documents/` private files are not tracked.
- `vector_store/` is not tracked.
- `OPENAI_API_KEY` is configured in Render, not committed.
- `ALLOWED_ORIGINS` is set to the final Render URL.
- `/health` returns `{"ok": true, "app": "Ask Anish"}`.
