# Career Document Library

This folder is for local source-of-truth career documents used to build the RAG index.

Suggested local folders:

- `resumes/` - resumes, master resumes, tailored resumes
- `linkedin/` - LinkedIn profile PDFs or exports
- `projects/` - project writeups, case studies, portfolio notes
- `github/` - optional manual GitHub exports or repo notes

Supported formats:

- `.pdf`
- `.txt`
- `.md`

## Privacy

Do not commit private resumes, LinkedIn exports, transcripts, student information, private project notes, or generated indexes unless each file has been explicitly reviewed and approved for publication.

The repository `.gitignore` intentionally excludes document contents under this folder while allowing this README to be tracked.

## Ingestion

GitHub can be ingested automatically when `GITHUB_USERNAME` is set in `.env`.

Run this after adding or changing approved documents:

```bash
python ingest.py
```

The generated index is written to `vector_store/career_index.json`, which is also excluded from Git because it contains source text.
