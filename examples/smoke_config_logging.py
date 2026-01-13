from __future__ import annotations

import asyncio
import logging

from discord_intern.config import YamlConfigLoader
from discord_intern.config.models import ConfigLoadRequest
from discord_intern.logging import init_logging


async def main() -> None:
    config = await YamlConfigLoader().load(ConfigLoadRequest(yaml_path="examples/config.yaml"))
    init_logging(config.logging)

    logger = logging.getLogger("smoke")
    logger.info("Config loaded dry_run=%s", config.app.dry_run)
    logger.info("Logging level=%s", config.logging.level)


if __name__ == "__main__":
    asyncio.run(main())
