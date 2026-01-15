# Module Design: Knowledge Base

## Purpose

The Knowledge Base module ingests content from local text files and web pages referenced by links, builds a small startup index describing each source, and provides retrieval helpers so the AI module can select and load only the most relevant content for a given query.

The KB module is designed for fast source selection and bounded retrieval.

## Responsibilities

- Ingest sources from:
  - A folder of local text files
  - HTTP/HTTPS links referenced inside those files
- On each startup:
  - Analyze and summarize sources
  - Produce a small index artifact that can be searched quickly
- Provide retrieval helpers to the AI module:
  - Provide the full index text for the AI module to send to the LLM for source selection
  - Load full content for a selected file path or URL identifier
- Enforce safety and performance constraints:
  - Strict timeouts for web fetches
  - Caching for web content
  - Size bounds for loaded content

## Terminology

- **Source**: a file path or URL.
- **Index**: a compact, searchable description per source.

## Runtime configuration

All configuration is loaded from `config.yaml` with environment-variable overrides as specified in [`./configuration.md`](./configuration.md).

The Knowledge Base reads these keys under the `kb` section:

- `kb.sources_dir`
- `kb.index_path`
- `kb.links_file_path`
- `kb.web_fetch_timeout_seconds`
- `kb.web_fetch_cache_dir`
- `kb.max_source_bytes`

## Index artifact format

The index is intended to be small and fast to read at runtime. It MUST be a **UTF-8 text file**. The AI module may send the full index text to the LLM for source selection, so the format should prioritize readability and stable diffs.

The index MUST be a sequence of entries. Each entry MUST be:

- A single line containing the source identifier:
  - For files: the file path relative to the knowledge base folder
  - For web sources: the full URL
- Followed by one or more lines of free-text description for source selection

Entries MUST be separated by at least one blank line.

See the example index file: `examples/kb_index.txt`.

Notes:
- The identifier line must be stable across runs for citation stability.
- Keep descriptions short and focused on when the source is relevant.

## Public interfaces

The AI module should not know about filesystem scanning or HTTP caching details. It should call a small retrieval API.

See `src/community_intern/kb/interfaces.py` `KnowledgeBase`.

## Ingestion

### File scanning

- Scan `kb.sources_dir` for text files.
- Read `kb.links_file_path` to obtain a list of URL sources (one URL per line).
- Note: The `links.txt` file itself is NOT summarized; only the content of the URLs it lists is processed.

### URL fetching

- Fetch with strict timeout `kb.web_fetch_timeout_seconds`.
- Use a headless browser to wait for dynamic content (`networkidle` event) and capture the full DOM state.
- Extract content from the `<body>` tag.
- Cache responses in memory or on disk using a hash of the URL as the cache key and file name.
- Enforce max download size `kb.max_source_bytes` and reject larger responses.

### Index generation

For each source:
- Use an LLM to produce a short description focused on what the source covers and when it is relevant.
- The LLM summarization MUST be performed via the AI module's dedicated summarization method. See [`./module-ai-response.md`](./module-ai-response.md).

The index generation step should be deterministic as much as possible to avoid noisy diffs.

## Retrieval

The Knowledge Base does not decide which sources are relevant.

At runtime, the AI module:

- Loads the index artifact as plain text from the Knowledge Base.
- Sends the index text and the user query to the LLM to select a relevant list of file paths and/or URLs.
- Requests full content for those selected identifiers from the Knowledge Base.

## Citation design

The KB module must maintain `source_id` continuity:

- The AI module cites sources using the identifier line from the index.
- Optionally, each snippet may later include location metadata:
  - file line ranges
  - URL fragment identifiers

For now, the identifier plus an optional quoted excerpt is sufficient.

## Error handling

- If index is missing or invalid:
  - Fail startup or rebuild index automatically.
- If a web source fetch fails:
  - Log and continue; do not block answering if other sources are available.
- If no selected sources can be loaded:
  - Return empty source content; the AI module decides whether to reply.

## Observability

Logs:

- Index build:
  - `sources_total`, `file_sources_total`, `url_sources_total`, `duration_ms`
  - per-source failures with `source_id` and reason
- Retrieval:
  - `query`, `selected_sources`, `loaded_sources`, `duration_ms`
  - cache hits/misses for URL fetches

Metrics:

- `kb_index_build_total{result=success|error}`
- `kb_web_fetch_total{result=success|timeout|error|cache_hit}`
- `kb_retrieval_selected_sources_histogram`
- `kb_retrieval_loaded_sources_histogram`

## Test plan

- Unit tests:
  - Link reading from links file
  - Index read/write and format validation
- Integration tests:
  - Build index from a sample folder with a mix of files and URLs
  - Loading selected source content returns stable identifiers
