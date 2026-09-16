from __future__ import annotations

import base64
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI
from pypdf import PdfReader

load_dotenv(override=True)

ROOT = Path(__file__).resolve().parent
DOCUMENTS_DIR = ROOT / "documents"
VECTOR_DIR = ROOT / "vector_store"
INDEX_PATH = VECTOR_DIR / "career_index.json"

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
CHUNK_WORDS = int(os.getenv("RAG_CHUNK_WORDS", "420"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "80"))
TOP_K = int(os.getenv("RAG_TOP_K", "6"))
MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.16"))
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_MAX_REPOS = int(os.getenv("GITHUB_MAX_REPOS", "12"))
GITHUB_README_CHARS = int(os.getenv("GITHUB_README_CHARS", "6000"))
GITHUB_INCLUDE_FORKS = os.getenv("GITHUB_INCLUDE_FORKS", "false").lower() == "true"

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}


@dataclass
class RetrievedChunk:
    text: str
    source: str
    source_type: str
    page: int | None
    chunk_id: str
    score: float

    @property
    def source_label(self) -> str:
        if self.page:
            return f"{self.source} p.{self.page}"
        return self.source


def discover_source_files() -> list[Path]:
    files: list[Path] = []
    for path in [ROOT / "summary.txt", ROOT / "linkedin.pdf"]:
        if path.exists():
            files.append(path)

    if DOCUMENTS_DIR.exists():
        for path in DOCUMENTS_DIR.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                if path.name.lower().startswith("readme"):
                    continue
                files.append(path)

    return sorted(set(files), key=lambda p: str(p.relative_to(ROOT)))


def source_signature(files: list[Path]) -> list[dict]:
    signature = []
    for path in files:
        stat = path.stat()
        signature.append(
            {
                "path": str(path.relative_to(ROOT)),
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
            }
        )
    if GITHUB_USERNAME:
        signature.append(
            {
                "path": f"github:{GITHUB_USERNAME}",
                "mtime_ns": 0,
                "size": GITHUB_MAX_REPOS,
                "include_forks": GITHUB_INCLUDE_FORKS,
                "readme_chars": GITHUB_README_CHARS,
            }
        )
    return signature


def read_pdf(path: Path) -> list[dict]:
    pages = []
    reader = PdfReader(str(path))
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = normalize_text(text)
        if text:
            pages.append({"text": text, "page": page_number})
    return pages


def read_text_file(path: Path) -> list[dict]:
    text = normalize_text(path.read_text(encoding="utf-8", errors="ignore"))
    return [{"text": text, "page": None}] if text else []


def github_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def github_get(url: str) -> dict | list | None:
    try:
        response = requests.get(url, headers=github_headers(), timeout=20)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        print(f"GitHub ingestion skipped for {url}: {exc}", flush=True)
        return None


def format_github_profile(profile: dict) -> str:
    fields = [
        f"GitHub profile for {profile.get('name') or profile.get('login')}",
        f"Username: {profile.get('login')}",
        f"Bio: {profile.get('bio') or 'Not provided'}",
        f"Company: {profile.get('company') or 'Not provided'}",
        f"Location: {profile.get('location') or 'Not provided'}",
        f"Public repos: {profile.get('public_repos')}",
        f"Followers: {profile.get('followers')}",
        f"Profile URL: {profile.get('html_url')}",
    ]
    return "\n".join(fields)


def format_repo_summary(repo: dict, readme: str | None) -> str:
    topics = repo.get("topics") or []
    fields = [
        f"Repository: {repo.get('full_name')}",
        f"URL: {repo.get('html_url')}",
        f"Description: {repo.get('description') or 'Not provided'}",
        f"Primary language: {repo.get('language') or 'Not provided'}",
        f"Topics: {', '.join(topics) if topics else 'Not provided'}",
        f"Stars: {repo.get('stargazers_count')}",
        f"Fork: {repo.get('fork')}",
        f"Created: {repo.get('created_at')}",
        f"Updated: {repo.get('updated_at')}",
    ]
    if readme:
        fields.extend(["README excerpt:", readme[:GITHUB_README_CHARS]])
    return "\n".join(fields)


def fetch_repo_readme(repo_full_name: str) -> str | None:
    data = github_get(f"https://api.github.com/repos/{repo_full_name}/readme")
    if not isinstance(data, dict) or not data.get("content"):
        return None
    decoded = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
    return normalize_text(decoded)


def fetch_github_documents() -> list[dict]:
    if not GITHUB_USERNAME:
        return []

    documents = []
    profile = github_get(f"https://api.github.com/users/{GITHUB_USERNAME}")
    if isinstance(profile, dict):
        documents.append(
            {
                "text": format_github_profile(profile),
                "source": f"github/{GITHUB_USERNAME}-profile.md",
                "source_type": "github",
                "page": None,
            }
        )

    repos = github_get(
        f"https://api.github.com/users/{GITHUB_USERNAME}/repos"
        f"?sort=updated&direction=desc&per_page={min(GITHUB_MAX_REPOS, 100)}"
    )
    if not isinstance(repos, list):
        return documents

    selected_repos = [
        repo for repo in repos if GITHUB_INCLUDE_FORKS or not repo.get("fork")
    ][:GITHUB_MAX_REPOS]

    for repo in selected_repos:
        full_name = repo.get("full_name")
        if not full_name:
            continue
        readme = fetch_repo_readme(full_name)
        documents.append(
            {
                "text": format_repo_summary(repo, readme),
                "source": f"github/{full_name.replace('/', '__')}.md",
                "source_type": "github",
                "page": None,
            }
        )

    return documents


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_text(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    step = max(1, CHUNK_WORDS - CHUNK_OVERLAP)
    while start < len(words):
        chunk_words = words[start : start + CHUNK_WORDS]
        chunks.append(" ".join(chunk_words))
        if start + CHUNK_WORDS >= len(words):
            break
        start += step
    return chunks


def file_documents(files: list[Path]) -> list[dict]:
    documents = []
    for path in files:
        relative_path = str(path.relative_to(ROOT))
        suffix = path.suffix.lower()
        parts = read_pdf(path) if suffix == ".pdf" else read_text_file(path)
        source_type = "pdf" if suffix == ".pdf" else "text"

        for part in parts:
            documents.append(
                {
                    "text": part["text"],
                    "source": relative_path,
                    "source_type": source_type,
                    "page": part["page"],
                }
            )
    return documents


def build_chunks(files: list[Path]) -> list[dict]:
    chunks = []
    documents = file_documents(files) + fetch_github_documents()

    for document in documents:
        page = document["page"]
        for chunk_number, chunk in enumerate(chunk_text(document["text"]), start=1):
            chunks.append(
                {
                    "id": f"{document['source']}:{page or 'all'}:{chunk_number}",
                    "text": chunk,
                    "source": document["source"],
                    "source_type": document["source_type"],
                    "page": page,
                    "chunk_number": chunk_number,
                }
            )
    return chunks


def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    embeddings: list[list[float]] = []
    batch_size = 64
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        embeddings.extend(item.embedding for item in response.data)
    return embeddings


def build_index(force: bool = False) -> dict:
    files = discover_source_files()
    signature = source_signature(files)

    if not force:
        existing = load_index()
        if existing and existing.get("source_signature") == signature:
            return existing

    chunks = build_chunks(files)
    if not chunks:
        index = {
            "embedding_model": EMBEDDING_MODEL,
            "source_signature": signature,
            "chunks": [],
        }
        save_index(index)
        return index

    client = OpenAI()
    embeddings = embed_texts(client, [chunk["text"] for chunk in chunks])
    if len(chunks) != len(embeddings):
        raise RuntimeError("Embedding count did not match chunk count.")

    for chunk, embedding in zip(chunks, embeddings):
        chunk["embedding"] = embedding

    index = {
        "embedding_model": EMBEDDING_MODEL,
        "source_signature": signature,
        "chunks": chunks,
    }
    save_index(index)
    return index


def load_index() -> dict | None:
    if not INDEX_PATH.exists():
        return None
    with INDEX_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_index(index: dict) -> None:
    VECTOR_DIR.mkdir(exist_ok=True)
    with INDEX_PATH.open("w", encoding="utf-8") as f:
        json.dump(index, f)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve(question: str, top_k: int = TOP_K) -> list[RetrievedChunk]:
    index = build_index()
    chunks = index.get("chunks", [])
    if not chunks:
        return []

    client = OpenAI()
    query_embedding = client.embeddings.create(
        model=index.get("embedding_model", EMBEDDING_MODEL),
        input=question,
    ).data[0].embedding

    scored = []
    for chunk in chunks:
        score = cosine_similarity(query_embedding, chunk["embedding"])
        if score >= MIN_SCORE:
            scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        RetrievedChunk(
            text=chunk["text"],
            source=chunk["source"],
            source_type=chunk["source_type"],
            page=chunk["page"],
            chunk_id=chunk["id"],
            score=score,
        )
        for score, chunk in scored[:top_k]
    ]


def format_retrieved_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "No career evidence was retrieved for this question."

    blocks = []
    for number, chunk in enumerate(chunks, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[Evidence {number}]",
                    f"Source: {chunk.source_label}",
                    f"Relevance: {chunk.score:.3f}",
                    f"Text: {chunk.text}",
                ]
            )
        )
    return "\n\n".join(blocks)


def format_source_footer(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return ""

    seen = []
    for chunk in chunks:
        label = chunk.source_label
        if label not in seen:
            seen.append(label)

    return "\n\n_Grounded in: " + "; ".join(seen[:5]) + "_"
