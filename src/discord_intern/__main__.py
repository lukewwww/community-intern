from __future__ import annotations

import argparse
import asyncio
import logging

from discord_intern.adapters.discord import DiscordBotAdapter
from discord_intern.ai import MockAIClient
from discord_intern.config import YamlConfigLoader
from discord_intern.config.models import ConfigLoadRequest
from discord_intern.kb.impl import FileSystemKnowledgeBase
from discord_intern.logging import init_logging

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="discord-intern", description="Discord Intern bot runner")
    parser.add_argument(
        "--config",
        default="data/config/config.yaml",
        help="Path to config.yaml (default: data/config/config.yaml)",
    )
    parser.add_argument(
        "--no-dotenv",
        action="store_true",
        help="Disable loading .env (env overrides still apply)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to run")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Start the Discord bot")
    run_parser.add_argument(
        "--mock-reply-text",
        default=None,
        help="Override the default mock reply text",
    )
    run_parser.add_argument(
        "--run-seconds",
        type=float,
        default=None,
        help="Run the bot for N seconds then exit (useful for smoke testing).",
    )

    # Command: init_kb
    subparsers.add_parser("init_kb", help="Initialize Knowledge Base index")

    return parser


async def _stop_adapter_gracefully(adapter: DiscordBotAdapter, *, timeout_seconds: float = 15.0) -> None:
    try:
        await asyncio.wait_for(asyncio.shield(adapter.stop()), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning("app.shutdown_timeout timeout_seconds=%s", timeout_seconds)
    except Exception:
        logger.exception("app.shutdown_error")


async def _load_config(args: argparse.Namespace):
    loader = YamlConfigLoader()
    request = ConfigLoadRequest(
        yaml_path=args.config,
        dotenv_path=None if args.no_dotenv else ".env",
    )
    return await loader.load(request)


async def _run_bot(args: argparse.Namespace) -> None:
    config = await _load_config(args)
    init_logging(config.logging)
    logger.info("app.starting_bot dry_run=%s", config.app.dry_run)

    ai_client = MockAIClient(reply_text=args.mock_reply_text) if args.mock_reply_text else MockAIClient()
    adapter = DiscordBotAdapter(config=config, ai_client=ai_client)
    try:
        if args.run_seconds is not None:
            await adapter.run_for(seconds=args.run_seconds)
        else:
            await adapter.start()
    finally:
        await _stop_adapter_gracefully(adapter)


async def _init_kb(args: argparse.Namespace) -> None:
    config = await _load_config(args)
    init_logging(config.logging)
    logger.info("app.starting_kb_init")

    # Using MockAIClient for now as real one isn't integrated yet
    ai_client = MockAIClient()
    kb = FileSystemKnowledgeBase(config=config.kb, ai_client=ai_client)

    await kb.build_index()
    logger.info("app.kb_init_complete")


async def _main_async() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "run":
        await _run_bot(args)
    elif args.command == "init_kb":
        await _init_kb(args)


def main() -> None:
    try:
        asyncio.run(_main_async())
    except KeyboardInterrupt:
        logger.info("app.interrupted_by_user")


if __name__ == "__main__":
    main()
