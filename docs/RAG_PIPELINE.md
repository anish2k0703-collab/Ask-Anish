# RAG Pipeline

Ask Anish uses a simple local RAG pipeline designed for a personal digital-twin demo.

## Inputs

Supported local source files:

- `.pdf`
- `.txt`
- `.md`

Optional GitHub ingestion:

- Public profile metadata
- Recent repositories
- Repository README excerpts when available

## Index Build

Run:

```bash
python ingest.py
```

The ingestion process:

1. Discovers approved source files.
2. Extracts and normalizes text.
3. Splits text into overlapping chunks.
4. Embeds chunks with the configured OpenAI embedding model.
5. Stores chunks and embeddings in `vector_store/career_index.json`.

## Retrieval

At question time:

1. The question is embedded.
2. Cosine similarity is computed against indexed chunks.
3. Chunks above `RAG_MIN_SCORE` are sorted.
4. The top `RAG_TOP_K` chunks are injected into the grounding prompt.

## Evidence Rules

The assistant uses:

- Verified facts when exact details exist in retrieved evidence.
- Supported interpretations when the source supports a qualitative conclusion but not a metric.
- Unavailable-information handling when evidence is missing.

## Privacy Notes

Do not commit source documents or vector indexes unless every contained fact has been approved for publication. Vector indexes include raw chunk text and can expose private resume or LinkedIn content.

The UI redacts email addresses and phone numbers in source excerpts, but that does not make the original source files safe to publish.
