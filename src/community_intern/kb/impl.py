from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Sequence, Set

from community_intern.ai.interfaces import AIClient
from community_intern.config.models import KnowledgeBaseSettings
from community_intern.kb.interfaces import IndexEntry, SourceContent
from community_intern.kb.web_fetcher import WebFetcher

logger = logging.getLogger(__name__)


class FileSystemKnowledgeBase:
    def __init__(self, config: KnowledgeBaseSettings, ai_client: AIClient):
        self.config = config
        self.ai_client = ai_client
        self._url_pattern = re.compile(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*')

    async def load_index_text(self) -> str:
        """Load the startup-produced index artifact as plain text."""
        index_path = Path(self.config.index_path)
        if not index_path.exists():
            return ""
        return index_path.read_text(encoding="utf-8")

    async def load_index_entries(self) -> Sequence[IndexEntry]:
        """Load the startup-produced index artifact as structured entries."""
        text = await self.load_index_text()
        entries = []
        if not text:
            return entries

        # Split by double newlines to separate entries
        chunks = text.strip().split("\n\n")
        for chunk in chunks:
            lines = chunk.strip().split("\n")
            if not lines:
                continue
            source_id = lines[0].strip()
            description = "\n".join(lines[1:]).strip()
            entries.append(IndexEntry(source_id=source_id, description=description))
        return entries

    async def build_index(self) -> None:
        """Build the startup index artifact on disk."""
        logger.info("kb.build_index_start")
        sources_dir = Path(self.config.sources_dir)
        if not sources_dir.exists():
            logger.warning("kb.sources_dir_missing path=%s", sources_dir)
            return

        # 1. Gather sources
        file_sources: Set[Path] = set()
        url_sources: Set[str] = set()

        for file_path in sources_dir.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith("."):
                try:
                    text = file_path.read_text(encoding="utf-8")
                    file_sources.add(file_path)
                    # Extract URLs
                    found_urls = self._url_pattern.findall(text)
                    for url in found_urls:
                        # Simple cleanup of trailing punctuation
                        url = url.rstrip('.,;)"\'')
                        url_sources.add(url)
                except UnicodeDecodeError:
                    logger.warning("kb.file_decode_error path=%s", file_path)
                    continue

        logger.info("kb.sources_found files=%d urls=%d", len(file_sources), len(url_sources))

        # 2. Process sources and generate summaries
        entries: list[str] = []

        # Process files
        sorted_files = sorted(file_sources)
        total_files = len(sorted_files)
        total_items = total_files + len(url_sources)
        processed_count = 0

        for i, file_path in enumerate(sorted_files, 1):
            processed_count += 1
            rel_path = file_path.relative_to(sources_dir).as_posix()
            logger.info("kb.processing_progress current=%d total=%d type=file path=%s", processed_count, total_items, rel_path)
            try:
                text = file_path.read_text(encoding="utf-8")

                summary = await self.ai_client.summarize_for_kb_index(
                    source_id=rel_path,
                    text=text,
                    timeout_seconds=30.0 # Using a default timeout, ideally from config
                )
                entries.append(f"{rel_path}\n{summary}")
            except Exception as e:
                logger.error("kb.file_processing_error path=%s error=%s", file_path, e)

        # Process URLs
        # Use WebFetcher context manager to keep browser open for batch processing
        sorted_urls = sorted(url_sources)

        async with WebFetcher(self.config) as fetcher:
            for i, url in enumerate(sorted_urls, 1):
                processed_count += 1
                logger.info("kb.processing_progress current=%d total=%d type=url url=%s", processed_count, total_items, url)
                try:
                    text = await fetcher.fetch(url)
                    if not text:
                        continue

                    summary = await self.ai_client.summarize_for_kb_index(
                        source_id=url,
                        text=text,
                        timeout_seconds=30.0
                    )
                    entries.append(f"{url}\n{summary}")
                except Exception as e:
                    logger.error("kb.url_processing_error url=%s error=%s", url, e)

        # 3. Write index
        index_path = Path(self.config.index_path)
        index_path.parent.mkdir(parents=True, exist_ok=True)

        # Join with blank lines
        index_content = "\n\n".join(entries)
        index_path.write_text(index_content, encoding="utf-8")
        logger.info("kb.index_written path=%s entries=%d", index_path, len(entries))

    async def load_source_content(self, *, source_id: str) -> SourceContent:
        """Load full source content for a file path or URL identifier."""
        sources_dir = Path(self.config.sources_dir)

        # Check if it's a URL
        if source_id.startswith(("http://", "https://")):
             # Reuse WebFetcher logic (it handles caching)
             # Note: For single fetch, this will start/stop browser if not cached, which is heavy but safe.
             async with WebFetcher(self.config) as fetcher:
                 text = await fetcher.fetch(source_id)
                 return SourceContent(source_id=source_id, text=text)

        # Assume file path relative to sources_dir
        file_path = sources_dir / source_id
        try:
            if file_path.exists() and file_path.is_file():
                 text = file_path.read_text(encoding="utf-8")
                 return SourceContent(source_id=source_id, text=text)
        except Exception as e:
            logger.warning("kb.load_file_error path=%s error=%s", file_path, e)

        return SourceContent(source_id=source_id, text="")



