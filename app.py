import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from chat_engine import answer_question, stream_answer_question

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
MAX_QUESTION_CHARS = int(os.getenv("MAX_QUESTION_CHARS", "1200"))
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "20"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "3600"))
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
    if origin.strip()
]
request_log: dict[str, deque[float]] = defaultdict(deque)

app = FastAPI(title="Ask Anish", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "POST"],
    allow_headers=["Content-Type"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: list[ChatMessage] = Field(default_factory=list)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def enforce_rate_limit(request: Request) -> None:
    now = time.time()
    ip = client_ip(request)
    hits = request_log[ip]
    while hits and hits[0] <= now - RATE_LIMIT_WINDOW_SECONDS:
        hits.popleft()
    if len(hits) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait before asking another question.",
        )
    hits.append(now)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.head("/")
def index_head() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "app": "Ask Anish"}


@app.get("/health")
def render_health() -> dict:
    return health()


@app.post("/api/chat")
def chat(payload: ChatRequest, request: Request) -> dict:
    enforce_rate_limit(request)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    result = answer_question(
        message=message,
        history=[item.model_dump() for item in payload.history],
    )
    return {
        "answer": result.answer,
        "grounded": result.grounded,
        "sources": [
            {
                "title": source.title,
                "meta": source.meta,
                "kind": source.kind,
                "excerpt": source.excerpt,
                "supports": source.supports,
                "link": source.link,
            }
            for source in result.sources
        ],
        "suggestions": result.suggestions,
        "why": result.why,
    }


@app.post("/api/chat/stream")
def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    enforce_rate_limit(request)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    history = [item.model_dump() for item in payload.history]

    def events():
        for event in stream_answer_question(message=message, history=history):
            event_type = event.pop("type")
            yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
