# Troubleshooting

## Port Already In Use

Use another port:

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8001
```

Or stop the process on port `8000`:

```bash
lsof -ti :8000 | xargs kill
```

## Missing OpenAI API Key

If the assistant says it needs an OpenAI API key, confirm `.env` contains:

```text
OPENAI_API_KEY=...
```

Then restart the server.

## Empty Or Weak Answers

Rebuild the index:

```bash
python ingest.py
```

Confirm approved files exist under `documents/` locally or `GITHUB_USERNAME` is configured.

## Render Build Fails During Ingestion

Check that Render has:

- `OPENAI_API_KEY`
- `GITHUB_USERNAME` if relying on GitHub ingestion

If using private source documents, do not commit them. Use a reviewed public source bundle or a secure external storage strategy.

## 429 Too Many Requests

The app includes conservative per-IP rate limiting. Tune:

```text
RATE_LIMIT_REQUESTS
RATE_LIMIT_WINDOW_SECONDS
```

## CORS Errors

Set `ALLOWED_ORIGINS` to the deployed site origin. For local development:

```text
ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
```

## Streaming Does Not Appear

Use `/api/chat/stream`, not `/api/chat`, for server-sent events.

Check the browser network tab for an event-stream response containing:

- `status`
- `meta`
- `token`
- `done`
