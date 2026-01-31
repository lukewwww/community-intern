from __future__ import annotations

import argparse
import asyncio
import logging

from community_intern.adapters.discord import DiscordBotAdapter
from community_intern.ai_response import AIResponseService
from community_intern.config import YamlConfigLoader
from community_intern.config.models import ConfigLoadRequest
from community_intern.kb.impl import FileSystemKnowledgeBase
from community_intern.llm import LLMInvoker
from community_intern.logging import init_logging

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="community-intern", description="Community Intern bot runner")
    parser.add_argument(
        "--config",
        default="data/config/config.yaml",
        help="Path to config.yaml (default: data/config/config.yaml)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to run")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Start the Discord bot")
    run_parser.add_argument(
        "--run-seconds",
        type=float,
        default=None,
        help="Run the bot for N seconds then exit (useful for smoke testing).",
    )

    # Command: init_kb
    subparsers.add_parser("init_kb", help="Initialize Knowledge Base index")

    # Command: init_team_kb
    subparsers.add_parser("init_team_kb", help="Initialize team knowledge base")

    return parser


async def _stop_adapter_gracefully(adapter: DiscordBotAdapter, *, timeout_seconds: float = 15.0) -> None:
    try:
        await asyncio.wait_for(asyncio.shield(adapter.stop()), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning("Shutdown timed out while stopping the Discord adapter. timeout_seconds=%s", timeout_seconds)
    except Exception:
        logger.exception("Unexpected error during shutdown.")


def _log_index_task_result(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Knowledge base indexing failed.")


async def _load_config(args: argparse.Namespace):
    loader = YamlConfigLoader()
    request = ConfigLoadRequest(
        yaml_path=args.config,
    )
    return await loader.load(request)


def _build_kb_llm_invoker(config) -> LLMInvoker:
    llm_settings = config.kb.llm or config.ai_response.llm
    return LLMInvoker(
        llm=llm_settings,
        project_introduction=config.ai_response.project_introduction,
        llm_enable_image=config.ai_response.llm_enable_image,
        llm_image_adapter=config.ai_response.llm_image_adapter,
    )


async def _run_bot(args: argparse.Namespace) -> None:
    from community_intern.team_kb import QACaptureHandler, TeamKnowledgeManager

    config = await _load_config(args)
    init_logging(config.logging)
    logger.info("Starting application in bot mode. dry_run=%s", config.app.dry_run)

    # Initialize AI and KnowledgeBase with circular dependency injection
    ai_response = AIResponseService(config=config.ai_response)
    kb_llm_invoker = _build_kb_llm_invoker(config)
    team_llm_invoker = _build_kb_llm_invoker(config)
    kb = FileSystemKnowledgeBase(config=config.kb, llm_invoker=kb_llm_invoker)
    ai_response.set_kb(kb)

    # Initialize team knowledge capture
    team_kb = TeamKnowledgeManager(config=config.kb, llm_invoker=team_llm_invoker)
    qa_capture_handler = QACaptureHandler(
        manager=team_kb,
        llm_enable_image=config.ai_response.llm_enable_image,
        image_download_timeout_seconds=config.ai_response.image_download_timeout_seconds,
        image_download_max_retries=config.ai_response.image_download_max_retries,
    )

    index_task = asyncio.create_task(kb.build_index())
    index_task.add_done_callback(_log_index_task_result)
    kb.set_team_kb_manager(team_kb)
    kb.start_runtime_refresh()

    adapter = DiscordBotAdapter(
        config=config,
        ai_client=ai_response,
        qa_capture_handler=qa_capture_handler,
    )
    try:
        if args.run_seconds is not None:
            await adapter.run_for(seconds=args.run_seconds)
        else:
            await adapter.start()
    finally:
        await _stop_adapter_gracefully(adapter)
        await kb.stop_runtime_refresh()
        if index_task and not index_task.done():
            index_task.cancel()
            try:
                await index_task
            except asyncio.CancelledError:
                logger.info("Knowledge base indexing task cancelled during shutdown.")


async def _init_kb(args: argparse.Namespace) -> None:
    config = await _load_config(args)
    init_logging(config.logging)
    logger.info("Starting knowledge base indexing.")

    kb_llm_invoker = _build_kb_llm_invoker(config)
    kb = FileSystemKnowledgeBase(config=config.kb, llm_invoker=kb_llm_invoker)

    await kb.build_index()
    logger.info("Knowledge base indexing completed.")


async def _init_team_kb(args: argparse.Namespace) -> None:
    from community_intern.team_kb import TeamKnowledgeManager

    config = await _load_config(args)
    init_logging(config.logging)
    logger.info("Starting team knowledge base initialization.")

    team_llm_invoker = _build_kb_llm_invoker(config)
    team_kb = TeamKnowledgeManager(config=config.kb, llm_invoker=team_llm_invoker)

    await team_kb.regenerate()
    logger.info("Team knowledge base initialization completed.")


async def _main_async() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "run":
        await _run_bot(args)
    elif args.command == "init_kb":
        await _init_kb(args)
    elif args.command == "init_team_kb":
        await _init_team_kb(args)


def main() -> None:
    try:
        asyncio.run(_main_async())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")


if __name__ == "__main__":
    main()
