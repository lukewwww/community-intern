from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Protocol

from community_intern.llm import LLMInvoker, LLMTextResult
from community_intern.llm.prompts import compose_system_prompt
from community_intern.knowledge_cache.io import atomic_write_json, build_index_entries, encode_cache, read_cache_file, write_index_file
from community_intern.knowledge_cache.models import CacheRecord, CacheState, SchemaVersion, SourceType
from community_intern.knowledge_cache.utils import format_rfc3339, utc_now

logger = logging.getLogger(__name__)


class SourceProvider(Protocol):
    async def discover(self, *, now: datetime) -> Dict[str, SourceType]:
        ...

    async def init_record(self, *, source_id: str, now: datetime) -> CacheRecord | None:
        ...

    async def refresh(self, *, cache: CacheState, now: datetime) -> bool:
        ...

    async def load_text(self, *, source_id: str) -> str | None:
        ...


class KnowledgeIndexer:
    def __init__(
        self,
        *,
        cache_path: str,
        index_path: str,
        index_prefix: str,
        summarization_prompt: str,
        summarization_concurrency: int,
        llm_invoker: LLMInvoker,
        providers: Iterable[SourceProvider],
        source_type_order: list[SourceType],
    ) -> None:
        self._cache_path = Path(cache_path)
        self._index_path = Path(index_path)
        self._index_prefix = index_prefix
        self._summarization_prompt = summarization_prompt
        self._summarization_concurrency = max(1, int(summarization_concurrency))
        self._llm_invoker = llm_invoker
        self._providers = list(providers)
        self._source_type_order = source_type_order

        self._lock = asyncio.Lock()
        self._summary_semaphore = asyncio.Semaphore(self._summarization_concurrency)

    async def run_once(self) -> None:
        async with self._lock:
            await self._run_once_locked()

    async def notify_changed(self, source_id: str) -> None:
        _ = source_id
        await self.run_once()

    async def _run_once_locked(self) -> None:
        run_started = time.monotonic()
        stages_total = 4

        now = utc_now()

        stage = 1
        stage_started = time.monotonic()
        logger.info("KB index stage %s/%s: load cache.", stage, stages_total)
        cache = read_cache_file(self._cache_path)
        if cache.schema_version != SchemaVersion:
            cache = CacheState(schema_version=SchemaVersion, generated_at=format_rfc3339(now), sources={})
        logger.debug(
            "KB index load cache completed. path=%s sources=%s elapsed_ms=%s",
            self._cache_path,
            len(cache.sources),
            int((time.monotonic() - stage_started) * 1000),
        )

        stage = 2
        stage_started = time.monotonic()
        logger.info("KB index stage %s/%s: discover sources.", stage, stages_total)
        discovered, owner = await self._discover_sources(now=now)
        logger.info(
            "KB index discover completed. sources=%s elapsed_ms=%s",
            len(discovered),
            int((time.monotonic() - stage_started) * 1000),
        )

        stage = 3
        stage_started = time.monotonic()
        logger.info("KB index stage %s/%s: reconcile and refresh providers.", stage, stages_total)
        changed = False
        changed |= await self._reconcile(cache=cache, now=now, discovered=discovered, owner=owner)

        for provider_idx, provider in enumerate(self._providers, start=1):
            provider_name = type(provider).__name__
            logger.info(
                "KB index stage %s/%s: provider refresh %s/%s. provider=%s",
                stage,
                stages_total,
                provider_idx,
                len(self._providers),
                provider_name,
            )
            try:
                provider_changed = await provider.refresh(cache=cache, now=now)
            except Exception:
                logger.exception("Indexer provider refresh failed.")
                provider_changed = False
            if provider_changed:
                changed = True

        if changed:
            logger.debug("KB index persist started.")
            self._persist(cache=cache, now=now)
            logger.debug("KB index persist completed. cache_path=%s index_path=%s", self._cache_path, self._index_path)

        logger.info(
            "KB index reconcile/refresh completed. changed=%s elapsed_ms=%s",
            changed,
            int((time.monotonic() - stage_started) * 1000),
        )

        stage = 4
        logger.info("KB index stage %s/%s: summarize pending sources.", stage, stages_total)
        await self._summarize_pending(cache=cache, now=now, owner=owner)
        logger.info("KB index stage %s/%s completed.", stage, stages_total)
        logger.info("KB index run completed. elapsed_ms=%s", int((time.monotonic() - run_started) * 1000))

    async def _discover_sources(self, *, now: datetime) -> tuple[Dict[str, SourceType], Dict[str, SourceProvider]]:
        combined: Dict[str, SourceType] = {}
        owner: Dict[str, SourceProvider] = {}
        for provider in self._providers:
            mapping = await provider.discover(now=now)
            for source_id, source_type in mapping.items():
                if source_id in combined:
                    raise ValueError(f"Duplicate source_id discovered: {source_id}")
                combined[source_id] = source_type
                owner[source_id] = provider
        return combined, owner

    async def _reconcile(
        self,
        *,
        cache: CacheState,
        now: datetime,
        discovered: Dict[str, SourceType],
        owner: Dict[str, SourceProvider],
    ) -> bool:
        changed = False

        for source_id in list(cache.sources.keys()):
            if source_id not in discovered:
                cache.sources.pop(source_id, None)
                changed = True

        init_candidates: list[tuple[str, SourceType, SourceProvider]] = []
        for source_id, source_type in discovered.items():
            record = cache.sources.get(source_id)
            if record is None or record.source_type != source_type:
                provider = owner.get(source_id)
                if provider is None:
                    continue
                init_candidates.append((source_id, source_type, provider))

        if init_candidates:
            logger.info("KB index init new sources. pending=%s", len(init_candidates))

        for idx, (source_id, source_type, provider) in enumerate(init_candidates, start=1):
            provider_name = type(provider).__name__
            logger.info(
                "KB index init source %s/%s. source_id=%s type=%s provider=%s",
                idx,
                len(init_candidates),
                source_id,
                source_type,
                provider_name,
            )
            started = time.monotonic()
            initialized = await provider.init_record(source_id=source_id, now=now)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if initialized is None:
                logger.warning(
                    "KB index init source failed. source_id=%s type=%s provider=%s elapsed_ms=%s",
                    source_id,
                    source_type,
                    provider_name,
                    elapsed_ms,
                )
                continue
            cache.sources[source_id] = initialized
            changed = True
            logger.debug(
                "KB index init source completed. source_id=%s type=%s provider=%s elapsed_ms=%s",
                source_id,
                source_type,
                provider_name,
                elapsed_ms,
            )

        if changed:
            cache.generated_at = format_rfc3339(now)
        return changed

    async def _summarize_pending(
        self,
        *,
        cache: CacheState,
        now: datetime,
        owner: Dict[str, SourceProvider],
    ) -> None:
        tasks = []
        pending: list[tuple[str, CacheRecord, SourceProvider]] = []
        for source_id, record in cache.sources.items():
            if not record.summary_pending:
                continue
            provider = owner.get(source_id)
            if provider is None:
                continue
            pending.append((source_id, record, provider))

        if not pending:
            logger.info("KB index summarize pending. pending=0")
            return

        logger.info(
            "KB index summarize pending. pending=%s concurrency=%s",
            len(pending),
            self._summarization_concurrency,
        )

        for idx, (source_id, record, provider) in enumerate(pending, start=1):
            logger.debug("KB index summarize queued %s/%s. source_id=%s", idx, len(pending), source_id)
            tasks.append(
                asyncio.create_task(
                    self._summarize_one(
                        cache=cache,
                        record=record,
                        source_id=source_id,
                        provider=provider,
                        now=now,
                        position=idx,
                        total=len(pending),
                    )
                )
            )
        if tasks:
            await asyncio.gather(*tasks)

    async def _summarize_one(
        self,
        *,
        cache: CacheState,
        record: CacheRecord,
        source_id: str,
        provider: SourceProvider,
        now: datetime,
        position: int,
        total: int,
    ) -> None:
        async with self._summary_semaphore:
            logger.info("KB index summarize %s/%s: start. source_id=%s", position, total, source_id)
            started = time.monotonic()
            try:
                text = await provider.load_text(source_id=source_id)
                if not text or not text.strip():
                    logger.warning("KB index summarize %s/%s: empty source text. source_id=%s", position, total, source_id)
                    return
                system_prompt = compose_system_prompt(
                    self._summarization_prompt,
                    self._llm_invoker.project_introduction,
                )
                logger.debug(
                    "KB index summarize %s/%s: invoking LLM. source_id=%s text_chars=%s system_prompt_chars=%s",
                    position,
                    total,
                    source_id,
                    len(text),
                    len(system_prompt),
                )
                result = await self._llm_invoker.invoke_llm(
                    system_prompt=system_prompt,
                    user_content=text,
                    response_model=LLMTextResult,
                )
                summary = result.text.strip()
            except Exception:
                logger.exception("Indexer summarization failed. source_id=%s", source_id)
                return
            finally:
                logger.debug(
                    "KB index summarize %s/%s: finished LLM call. source_id=%s elapsed_ms=%s",
                    position,
                    total,
                    source_id,
                    int((time.monotonic() - started) * 1000),
                )

        current = cache.sources.get(source_id)
        if current is not record or not current.summary_pending:
            return
        current.summary_text = summary
        current.last_indexed_at = format_rfc3339(now)
        current.summary_pending = False
        self._persist(cache=cache, now=now)
        logger.info(
            "KB index summarize %s/%s: saved. source_id=%s summary_chars=%s",
            position,
            total,
            source_id,
            len(summary),
        )

    def _persist(self, *, cache: CacheState, now: datetime) -> None:
        cache.generated_at = format_rfc3339(now)
        atomic_write_json(self._cache_path, encode_cache(cache))
        entries = build_index_entries(
            cache,
            source_types=self._source_type_order,
            prefix=self._index_prefix,
        )
        write_index_file(self._index_path, entries)
