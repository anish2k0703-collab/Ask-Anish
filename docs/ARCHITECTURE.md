# Architecture

Ask Anish is a FastAPI application serving a custom static frontend and a Python RAG backend.

## Runtime Components

- `app.py`: HTTP routes, health checks, static asset serving, CORS, and rate limiting.
- `static/`: the browser UI, including streaming chat behavior and source panels.
- `chat_engine.py`: retrieval orchestration, OpenAI chat calls, SSE event generation, source cards, suggestions, and why explanations.
- `rag.py`: file discovery, text extraction, chunking, embeddings, local vector index, and cosine-similarity retrieval.
- `context.py`: system prompt, voice rules, evidence hierarchy, and safety boundaries.
- `tools.py`: optional notification tools for contact capture and unknown questions.

## Request Flow

1. The browser posts the message and bounded history to `/api/chat/stream`.
2. FastAPI validates question length and rate limits by IP.
3. `chat_engine.py` retrieves relevant evidence through `rag.py`.
4. Retrieved evidence is injected into a grounding message.
5. OpenAI streams answer tokens back to the server.
6. FastAPI emits server-sent events:
   - `status`
   - `meta`
   - `token`
   - `done`
7. The frontend updates one stable assistant message instead of rebuilding the whole chat.

## Source Handling

The application intentionally separates answer text from citation display. The assistant is instructed not to write raw paths, chunk IDs, similarity scores, or grounding footers. The UI receives friendly source metadata and displays it in expandable source cards.

## Deployment Shape

Render runs one Python web service:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

The included `render.yaml` builds dependencies and rebuilds the RAG index during deployment.
