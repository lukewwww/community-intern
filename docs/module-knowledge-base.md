# Module Design: Knowledge Base (Ingestion + Startup Index + Retrieval)

## Purpose

The Knowledge Base (KB) module ingests content from local text files and web pages referenced by links, builds a small startup index describing each source, and provides retrieval helpers so the AI module can select and load only the most relevant content for a given query.

The KB module is designed for **fast routing** (index-first) and **bounded retrieval** (minimum necessary context, with citations).

## Responsibilities

- Ingest sources from:
  - A folder of local text files
  - HTTP/HTTPS links referenced inside those files
- On each startup:
  - Analyze and summarize sources
  - Produce a small index artifact (JSON) that can be searched quickly
- Provide retrieval helpers to the AI module:
  - Select relevant sources for a query using the index
  - Load content from those sources
  - Extract ranked snippets suitable for grounding and citation
- Enforce safety and performance constraints:
  - Strict timeouts for web fetches
  - Caching for web content
  - Size bounds for loaded content and snippets

## Terminology

- **Source**: a file path or URL.
- **Index**: a compact, searchable summary per source (identity, tags, suggested questions).
- **Snippet**: a short excerpt of source text returned to the AI module for grounding.

## Runtime configuration

All configuration is loaded from `config.yaml` with environment-variable overrides as specified in `docs/configuration.md`.

The Knowledge Base reads these keys (under the `kb` section):

- `kb.sources_dir`
- `kb.index_path`
- `kb.web_fetch_timeout_seconds`
- `kb.web_fetch_cache_dir`
- `kb.max_source_bytes`
- `kb.max_snippet_chars`
- `kb.max_snippets_per_query`
- `kb.max_sources_per_query`

## Index artifact format (JSON)

The index is intended to be small and fast to read at runtime. It MUST include:

- Source identity: `source_id`, `type` (`file` or `url`), `path` or `url`
- Short summary: 5–15 lines describing what the source covers
- Topic tags / keywords: small controlled set for routing
- Suggested questions: examples the source is good at answering

Recommended JSON shape:

```json
{
  "version": 1,
  "generated_at": "2026-01-12T00:00:00Z",
  "sources": [
    {
      "source_id": "file:docs/setup.txt",
      "type": "file",
      "path": "docs/setup.txt",
      "summary": ["..."],
      "tags": ["..."],
      "suggested_questions": ["..."]
    },
    {
      "source_id": "url:https://example.com/guide",
      "type": "url",
      "url": "https://example.com/guide",
      "summary": ["..."],
      "tags": ["..."],
      "suggested_questions": ["..."]
    }
  ]
}
```

The index artifact MUST be JSON.

See the example index file: `examples/kb_index.json`.

Notes:
- `source_id` must be stable across runs for citation stability.
- `summary` is a list of lines to keep index diffs readable.
- Tags should come from a controlled vocabulary to avoid tag explosion.

## Public interfaces (used by AI module)

The AI module should not know about filesystem scanning or HTTP caching details. It should call a small retrieval API.

See:

- `src/discord_intern/kb/interfaces.py` (`KnowledgeBase`, `Source`, `Snippet`)

## Ingestion (startup)

### File scanning

- Scan `kb.sources_dir` for text files.
- Read file content with a hard size cap (`kb.max_source_bytes`).
- Extract embedded HTTP/HTTPS links from file content to form URL sources.

### URL fetching

- Fetch with strict timeout (`kb.web_fetch_timeout_seconds`).
- Cache responses (memory or disk) keyed by URL and fetch timestamp.
- Enforce max download size (`kb.max_source_bytes`) and reject larger responses.

### Index generation

For each source:
- Produce a short summary (5–15 lines) and tags.
- Include suggested questions for routing and debugging.

Implementation options for summarization:
- Initially: lightweight heuristic summarization (headings + key lines).
- Later: LLM-assisted summarization (run once at startup, bounded cost).

The index generation step should be deterministic as much as possible to avoid noisy diffs.

## Retrieval (runtime, index-first)

### Step 1: source selection

Given a query:
- Search the index (keyword/tag match + optional simple scoring).
- Select top `kb.max_sources_per_query` sources.

### Step 2: snippet extraction

For each selected source:
- Load the content (file read or cached web page).
- Extract a bounded set of snippets relevant to the query.

Initial snippet extraction strategy (simple and robust):
- Split content into paragraphs/sections.
- Score each chunk by term overlap with query tokens.
- Return top K chunks across all sources.

### Step 3: bounding and deduplication

- Deduplicate snippets by normalized text.
- Truncate to `kb.max_snippets_per_query`.
- Ensure each snippet is at most `kb.max_snippet_chars`.

## Citation design

The KB module must maintain `source_id` continuity:

- The AI module cites sources using `source_id`.
- Optionally, each snippet may later include location metadata:
  - file line ranges
  - URL fragment identifiers

For now, `source_id` plus an optional quoted excerpt is sufficient.

## Error handling

- If index is missing or invalid:
  - Fail startup (recommended) or rebuild index automatically.
- If a web source fetch fails:
  - Log and continue; do not block answering if other sources are available.
- If no sources/snippets are found:
  - Return an empty snippet list; the AI module decides whether to reply.

## Observability

Logs (structured):

- Index build:
  - `sources_total`, `file_sources_total`, `url_sources_total`, `duration_ms`
  - per-source failures with `source_id` and reason
- Retrieval:
  - `query`, `selected_sources`, `snippets_returned`, `duration_ms`
  - cache hits/misses for URL fetches

Metrics (recommended):

- `kb_index_build_total{result=success|error}`
- `kb_web_fetch_total{result=success|timeout|error|cache_hit}`
- `kb_retrieval_selected_sources_histogram`
- `kb_retrieval_snippets_histogram`

## Test plan

- Unit tests:
  - Link extraction from file content
  - Index read/write and schema validation
  - Source selection scoring
  - Snippet extraction and bounding
- Integration tests:
  - Build index from a sample folder with a mix of files and URLs
  - Retrieval returns stable `source_id`s and bounded snippet sizes
