from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Literal, Optional, Tuple

import aiohttp

from community_intern.ai.interfaces import AIClient
from community_intern.config.models import KnowledgeBaseSettings
from community_intern.kb.web_fetcher import WebFetcher

logger = logging.getLogger(__name__)

SchemaVersion = 1
FetchStatus = Literal["success", "not_modified", "timeout", "error"]


@dataclass(slots=True)
class FileMetadata:
    rel_path: str
    size_bytes: int
    mtime_ns: int


@dataclass(slots=True)
class UrlMetadata:
    url: str
    last_fetched_at: str
    etag: Optional[str]
    last_modified: Optional[str]
    fetch_status: FetchStatus
    next_check_at: str


@dataclass(slots=True)
class CacheRecord:
    source_type: Literal["file", "url"]
    content_hash: str
    summary_text: str
    last_indexed_at: str
    summary_pending: bool = False
    file: Optional[FileMetadata] = None
    url: Optional[UrlMetadata] = None


@dataclass(slots=True)
class CacheState:
    schema_version: int
    generated_at: str
    sources: Dict[str, CacheRecord]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_rfc3339(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _hash_text(text: str) -> str:
    normalized = _normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _encode_record(record: CacheRecord) -> dict:
    payload = {
        "source_type": record.source_type,
        "content_hash": record.content_hash,
        "summary_text": record.summary_text,
        "last_indexed_at": record.last_indexed_at,
        "summary_pending": record.summary_pending,
    }
    if record.file:
        payload["file"] = {
            "rel_path": record.file.rel_path,
            "size_bytes": record.file.size_bytes,
            "mtime_ns": record.file.mtime_ns,
        }
    if record.url:
        payload["url"] = {
            "url": record.url.url,
            "last_fetched_at": record.url.last_fetched_at,
            "etag": record.url.etag,
            "last_modified": record.url.last_modified,
            "fetch_status": record.url.fetch_status,
            "next_check_at": record.url.next_check_at,
        }
    return payload


def _decode_record(payload: dict) -> CacheRecord:
    file_meta = payload.get("file")
    url_meta = payload.get("url")
    file_value = None
    url_value = None
    if file_meta:
        file_value = FileMetadata(
            rel_path=file_meta["rel_path"],
            size_bytes=int(file_meta["size_bytes"]),
            mtime_ns=int(file_meta["mtime_ns"]),
        )
    if url_meta:
        url_value = UrlMetadata(
            url=url_meta["url"],
            last_fetched_at=url_meta["last_fetched_at"],
            etag=url_meta.get("etag"),
            last_modified=url_meta.get("last_modified"),
            fetch_status=url_meta["fetch_status"],
            next_check_at=url_meta["next_check_at"],
        )
    return CacheRecord(
        source_type=payload["source_type"],
        content_hash=payload["content_hash"],
        summary_text=payload["summary_text"],
        last_indexed_at=payload["last_indexed_at"],
        summary_pending=bool(payload.get("summary_pending", False)),
        file=file_value,
        url=url_value,
    )


def _encode_cache(cache: CacheState) -> dict:
    return {
        "schema_version": cache.schema_version,
        "generated_at": cache.generated_at,
        "sources": {source_id: _encode_record(record) for source_id, record in cache.sources.items()},
    }


def _decode_cache(payload: dict) -> CacheState:
    sources_payload = payload.get("sources", {})
    sources: Dict[str, CacheRecord] = {}
    for source_id, record_payload in sources_payload.items():
        sources[source_id] = _decode_record(record_payload)
    return CacheState(
        schema_version=int(payload.get("schema_version", SchemaVersion)),
        generated_at=payload.get("generated_at", _format_rfc3339(_utc_now())),
        sources=sources,
    )


class KnowledgeBaseCacheManager:
    def __init__(self, config: KnowledgeBaseSettings, ai_client: AIClient, lock: asyncio.Lock):
        self._config = config
        self._ai_client = ai_client
        self._lock = lock
        self._runtime_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._persist_lock = asyncio.Lock()
        self._download_semaphore = asyncio.Semaphore(max(1, int(self._config.url_download_concurrency)))
        self._summary_semaphore = asyncio.Semaphore(max(1, int(self._config.summarization_concurrency)))

    async def build_index_incremental(self) -> None:
        async with self._lock:
            await self._run_tick(full_scan=True)

    def start_runtime_refresh(self) -> None:
        if self._runtime_task and not self._runtime_task.done():
            return
        self._stop_event.clear()
        self._runtime_task = asyncio.create_task(self._runtime_loop())

    async def stop_runtime_refresh(self) -> None:
        if not self._runtime_task:
            return
        self._stop_event.set()
        await self._runtime_task
        self._runtime_task = None

    async def _runtime_loop(self) -> None:
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                await self._runtime_tick()
            except Exception:
                logger.exception("Knowledge base runtime refresh tick failed.")
            elapsed = time.monotonic() - started
            sleep_seconds = max(0.0, self._config.runtime_refresh_tick_seconds - elapsed)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_seconds)
            except asyncio.TimeoutError:
                continue

    async def _runtime_tick(self) -> None:
        async with self._lock:
            await self._run_tick(full_scan=True)

    async def _run_tick(self, *, full_scan: bool) -> None:
        cache = self._load_cache()
        now = _utc_now()
        if full_scan:
            await self._process_full_scan(cache, now)

    def _load_cache(self) -> CacheState:
        cache_path = Path(self._config.index_cache_path)
        if not cache_path.exists():
            return CacheState(schema_version=SchemaVersion, generated_at=_format_rfc3339(_utc_now()), sources={})
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cache = _decode_cache(payload)
            if cache.schema_version != SchemaVersion:
                logger.warning(
                    "Knowledge base cache schema mismatch. expected=%s actual=%s",
                    SchemaVersion,
                    cache.schema_version,
                )
                return CacheState(schema_version=SchemaVersion, generated_at=_format_rfc3339(_utc_now()), sources={})
            return cache
        except Exception:
            logger.exception("Failed to load knowledge base cache file. path=%s", cache_path)
            return CacheState(schema_version=SchemaVersion, generated_at=_format_rfc3339(_utc_now()), sources={})

    def _write_cache(self, cache: CacheState) -> None:
        cache_path = Path(self._config.index_cache_path)
        _atomic_write_json(cache_path, _encode_cache(cache))

    def _write_index(self, entries: Iterable[str]) -> None:
        index_path = Path(self._config.index_path)
        entries_list = [entry for entry in entries if entry.strip()]
        content = "\n\n".join(entries_list)
        _atomic_write_text(index_path, content)
        logger.info("Knowledge base index written. path=%s entries=%d", index_path, len(entries_list))

    def _persist_cache_and_index(self, cache: CacheState, now: datetime) -> None:
        cache.generated_at = _format_rfc3339(now)
        self._write_cache(cache)
        index_entries = self._build_index_entries(cache)
        self._write_index(index_entries)

    async def _persist_cache_and_index_async(self, cache: CacheState, now: datetime) -> None:
        async with self._persist_lock:
            self._persist_cache_and_index(cache, now)

    async def _fetch_url_text(self, fetcher: WebFetcher, url: str, *, force_refresh: bool) -> str:
        async with self._download_semaphore:
            return await fetcher.fetch(url, force_refresh=force_refresh)

    async def _conditional_request_limited(
        self,
        *,
        url: str,
        etag: Optional[str],
        last_modified: Optional[str],
    ) -> Tuple[int, Optional[str], Optional[str]]:
        async with self._download_semaphore:
            return await self._conditional_request(url=url, etag=etag, last_modified=last_modified)

    async def _summarize_pending_sources(
        self,
        *,
        cache: CacheState,
        file_sources: Dict[str, Path],
        now: datetime,
    ) -> None:
        tasks = []
        fetcher = WebFetcher(self._config)
        for source_id, record in cache.sources.items():
            if not record.summary_pending:
                continue
            if record.source_type == "file" and record.file:
                file_path = file_sources.get(record.file.rel_path)
                if not file_path:
                    continue
                try:
                    text = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    logger.warning("Skipping non-UTF8 knowledge base file. path=%s", file_path)
                    continue
                except OSError as e:
                    logger.warning("Failed to read knowledge base file. path=%s error=%s", file_path, e)
                    continue
                content_hash = _hash_text(text)
                tasks.append(
                    asyncio.create_task(
                        self._summarize_source(
                            cache=cache,
                            record=record,
                            source_id=source_id,
                            text=text,
                            content_hash=content_hash,
                            now=now,
                        )
                    )
                )
            elif record.source_type == "url" and record.url:
                cached_text = fetcher.get_cached_content(record.url.url)
                if not cached_text:
                    continue
                content_hash = _hash_text(cached_text)
                tasks.append(
                    asyncio.create_task(
                        self._summarize_source(
                            cache=cache,
                            record=record,
                            source_id=source_id,
                            text=cached_text,
                            content_hash=content_hash,
                            now=now,
                        )
                    )
                )
        if tasks:
            await asyncio.gather(*tasks)

    async def _summarize_source(
        self,
        *,
        cache: CacheState,
        record: CacheRecord,
        source_id: str,
        text: str,
        content_hash: str,
        now: datetime,
    ) -> None:
        async with self._summary_semaphore:
            try:
                summary = await self._ai_client.summarize_for_kb_index(source_id=source_id, text=text)
            except Exception:
                logger.exception("Failed to summarize knowledge base source. source_id=%s", source_id)
                return
        async with self._persist_lock:
            current = cache.sources.get(source_id)
            if current is not record or not current.summary_pending:
                return
            current.summary_text = summary
            current.content_hash = content_hash
            current.last_indexed_at = _format_rfc3339(now)
            current.summary_pending = False
            self._persist_cache_and_index(cache, now)

    def _discover_file_sources(self) -> Dict[str, Path]:
        sources_dir = Path(self._config.sources_dir)
        if not sources_dir.exists():
            logger.warning("Knowledge base sources directory is missing. path=%s", sources_dir)
            return {}
        file_sources: Dict[str, Path] = {}
        for file_path in sources_dir.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith("."):
                try:
                    rel_path = file_path.relative_to(sources_dir).as_posix()
                    file_sources[rel_path] = file_path
                except ValueError:
                    continue
        return file_sources

    def _discover_url_sources(self) -> Dict[str, str]:
        links_file = Path(self._config.links_file_path)
        url_sources: Dict[str, str] = {}
        if not links_file.exists():
            return url_sources
        try:
            content = links_file.read_text(encoding="utf-8")
            for line in content.splitlines():
                url = line.strip()
                if url and not url.startswith("#"):
                    url_sources[url] = url
            return url_sources
        except Exception as e:
            logger.warning("Failed to read knowledge base links file. path=%s error=%s", links_file, e)
            return url_sources

    async def _process_full_scan(self, cache: CacheState, now: datetime) -> None:
        file_sources = self._discover_file_sources()
        url_sources = self._discover_url_sources()

        current_ids = set(file_sources.keys()) | set(url_sources.keys())
        for source_id in list(cache.sources.keys()):
            if source_id not in current_ids:
                cache.sources.pop(source_id, None)
                await self._persist_cache_and_index_async(cache, now)

        for rel_path, file_path in sorted(file_sources.items()):
            await self._process_file_source(
                cache=cache,
                rel_path=rel_path,
                file_path=file_path,
                now=now,
            )

        async with WebFetcher(self._config) as fetcher:
            tasks = []
            for url in sorted(url_sources.keys()):
                record = cache.sources.get(url)
                if record is None:
                    tasks.append(
                        asyncio.create_task(
                            self._create_url_source(
                                cache=cache,
                                url=url,
                                now=now,
                                fetcher=fetcher,
                            )
                        )
                    )
            if tasks:
                await asyncio.gather(*tasks)
        await self._refresh_urls(cache=cache, now=now)
        await self._summarize_pending_sources(cache=cache, file_sources=file_sources, now=now)

    async def _process_file_source(
        self,
        cache: CacheState,
        rel_path: str,
        file_path: Path,
        now: datetime,
    ) -> None:
        try:
            stat = file_path.stat()
        except OSError as e:
            logger.warning("Failed to stat knowledge base file. path=%s error=%s", file_path, e)
            return

        record = cache.sources.get(rel_path)
        if record is None:
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning("Skipping non-UTF8 knowledge base file. path=%s", file_path)
                return
            except OSError as e:
                logger.warning("Failed to read knowledge base file. path=%s error=%s", file_path, e)
                return

            content_hash = _hash_text(text)
            cache.sources[rel_path] = CacheRecord(
                source_type="file",
                content_hash=content_hash,
                summary_text="",
                last_indexed_at=_format_rfc3339(now),
                summary_pending=True,
                file=FileMetadata(rel_path=rel_path, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns),
            )
            await self._persist_cache_and_index_async(cache, now)
            return

        if record.source_type != "file":
            logger.warning("Cache record type mismatch for file source. source_id=%s", rel_path)
            cache.sources.pop(rel_path, None)
            await self._persist_cache_and_index_async(cache, now)
            return

        file_meta = record.file
        if not file_meta:
            file_meta = FileMetadata(rel_path=rel_path, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
        if file_meta.size_bytes == stat.st_size and file_meta.mtime_ns == stat.st_mtime_ns:
            return

        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.warning("Skipping non-UTF8 knowledge base file. path=%s", file_path)
            return
        except OSError as e:
            logger.warning("Failed to read knowledge base file. path=%s error=%s", file_path, e)
            return

        content_hash = _hash_text(text)
        record.file = FileMetadata(rel_path=rel_path, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
        if content_hash != record.content_hash or record.summary_pending:
            record.content_hash = content_hash
            record.summary_pending = True
            await self._persist_cache_and_index_async(cache, now)
            return
        await self._persist_cache_and_index_async(cache, now)

    async def _create_url_source(
        self,
        cache: CacheState,
        url: str,
        now: datetime,
        fetcher: WebFetcher,
    ) -> bool:
        text = await self._fetch_url_text(fetcher, url, force_refresh=True)
        if not text:
            logger.warning("Failed to fetch knowledge base URL source content. url=%s", url)
            return False
        content_hash = _hash_text(text)

        # Save intermediate state: download success, summary pending.
        # This ensures that if the process exits during LLM summarization,
        # we don't need to re-download the content next time.
        record = CacheRecord(
            source_type="url",
            content_hash=content_hash,
            summary_text="",
            last_indexed_at=_format_rfc3339(now),
            summary_pending=True,
            url=UrlMetadata(
                url=url,
                last_fetched_at=_format_rfc3339(now),
                etag=None,
                last_modified=None,
                fetch_status="success",
                next_check_at=_format_rfc3339(now + timedelta(seconds=self._config.url_refresh_min_interval_seconds)),
            ),
        )
        cache.sources[url] = record
        await self._persist_cache_and_index_async(cache, now)
        return True

    async def _refresh_urls(self, cache: CacheState, now: datetime) -> bool:
        url_records: list[CacheRecord] = []
        for source_id, record in cache.sources.items():
            if record.source_type != "url" or not record.url:
                continue
            if self._is_url_eligible(record, now):
                url_records.append(record)

        if not url_records:
            return False

        async with WebFetcher(self._config) as fetcher:
            tasks = [
                asyncio.create_task(self._refresh_single_url(cache=cache, record=record, now=now, fetcher=fetcher))
                for record in url_records
            ]
            results = await asyncio.gather(*tasks)
        return any(results)

    def _is_url_eligible(self, record: CacheRecord, now: datetime) -> bool:
        if not record.url:
            return False
        try:
            next_check = _parse_rfc3339(record.url.next_check_at)
        except Exception:
            return True
        if next_check <= now:
            return True
        return False

    async def _refresh_single_url(self, cache: CacheState, record: CacheRecord, now: datetime, fetcher: WebFetcher) -> bool:
        if not record.url:
            return False
        url_meta = record.url
        try:
            status, etag, last_modified = await self._conditional_request_limited(
                url=url_meta.url,
                etag=url_meta.etag,
                last_modified=url_meta.last_modified,
            )
        except asyncio.TimeoutError:
            if self._mark_url_failure(record, "timeout", now):
                await self._persist_cache_and_index_async(cache, now)
                return True
            return False
        except aiohttp.ClientError as e:
            logger.warning("URL refresh request failed. url=%s error=%s", url_meta.url, e)
            if self._mark_url_failure(record, "error", now):
                await self._persist_cache_and_index_async(cache, now)
                return True
            return False
        except Exception:
            logger.exception("Unexpected URL refresh error. url=%s", url_meta.url)
            if self._mark_url_failure(record, "error", now):
                await self._persist_cache_and_index_async(cache, now)
                return True
            return False

        if status == 304:
            url_meta.fetch_status = "not_modified"
            url_meta.last_fetched_at = _format_rfc3339(now)
            url_meta.next_check_at = _format_rfc3339(
                now + timedelta(seconds=self._config.url_refresh_min_interval_seconds)
            )
            await self._persist_cache_and_index_async(cache, now)
            return True

        if status != 200:
            logger.warning("Unexpected URL refresh status. url=%s status=%s", url_meta.url, status)
            if self._mark_url_failure(record, "error", now):
                await self._persist_cache_and_index_async(cache, now)
                return True
            return False

        text = await self._fetch_url_text(fetcher, url_meta.url, force_refresh=True)
        if not text:
            logger.warning("Failed to fetch knowledge base URL source content. url=%s", url_meta.url)
            if self._mark_url_failure(record, "error", now):
                await self._persist_cache_and_index_async(cache, now)
                return True
            return False

        content_hash = _hash_text(text)

        # Update metadata for successful download
        url_meta.etag = etag
        url_meta.last_modified = last_modified
        url_meta.fetch_status = "success"
        url_meta.last_fetched_at = _format_rfc3339(now)
        url_meta.next_check_at = _format_rfc3339(
            now + timedelta(seconds=self._config.url_refresh_min_interval_seconds)
        )

        should_summarize = content_hash != record.content_hash or record.summary_pending or not record.summary_text.strip()
        if should_summarize:
            record.content_hash = content_hash
            record.summary_pending = True
        else:
            record.content_hash = content_hash
        await self._persist_cache_and_index_async(cache, now)
        return True

    async def _conditional_request(
        self,
        url: str,
        etag: Optional[str],
        last_modified: Optional[str],
    ) -> Tuple[int, Optional[str], Optional[str]]:
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        timeout = aiohttp.ClientTimeout(total=self._config.web_fetch_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                status = response.status
                response_etag = response.headers.get("ETag")
                response_last_modified = response.headers.get("Last-Modified")
                response.release()
                return status, response_etag, response_last_modified

    def _mark_url_failure(self, record: CacheRecord, status: FetchStatus, now: datetime) -> bool:
        if not record.url:
            return False
        url_meta = record.url
        url_meta.fetch_status = status
        url_meta.next_check_at = _format_rfc3339(now + timedelta(seconds=self._config.runtime_refresh_tick_seconds))
        return True

    def _build_index_entries(self, cache: CacheState) -> Iterable[str]:
        file_entries = []
        url_entries = []
        for source_id, record in cache.sources.items():
            summary = record.summary_text.strip()
            if not summary:
                continue
            if record.source_type == "file":
                file_entries.append((source_id, summary))
            elif record.source_type == "url":
                url_entries.append((source_id, summary))

        entries = []
        for source_id, summary in sorted(file_entries, key=lambda item: item[0]):
            entries.append(f"{source_id}\n{summary}".strip())
        for source_id, summary in sorted(url_entries, key=lambda item: item[0]):
            entries.append(f"{source_id}\n{summary}".strip())
        return entries
