from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from discord_intern.ai.interfaces import AIConfig


class AppSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dry_run: bool = False


class FileRotationSettings(BaseModel):
    """
    Date-based rotation settings (daily).

    This maps cleanly to Python's standard library TimedRotatingFileHandler behavior.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    backup_count: int = 5


class FileLoggingSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = "data/logs/discord-intern.log"
    rotation: FileRotationSettings = Field(default_factory=FileRotationSettings)


class LoggingSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    level: str = "INFO"
    file: FileLoggingSettings = Field(default_factory=FileLoggingSettings)


class DiscordSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str = "REPLACE_ME"
    ai_timeout_seconds: float = 30


class KnowledgeBaseSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sources_dir: str = "data/knowledge-base/sources"
    index_path: str = "data/knowledge-base/index.txt"

    web_fetch_timeout_seconds: float = 10
    web_fetch_cache_dir: str = "data/knowledge-base/web-cache"

    max_source_bytes: int = 2_000_000
    max_snippet_chars: int = 1200
    max_snippets_per_query: int = 10
    max_sources_per_query: int = 6


class AppConfig(BaseModel):
    """
    Effective runtime configuration after applying all precedence rules.

    This is a schema contract only. Loading, validation, and override resolution are not
    implemented at this stage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    app: AppSettings = Field(default_factory=AppSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    discord: DiscordSettings = Field(default_factory=DiscordSettings)
    ai: AIConfig = Field(default_factory=AIConfig)
    kb: KnowledgeBaseSettings = Field(default_factory=KnowledgeBaseSettings)


@dataclass(frozen=True, slots=True)
class ConfigLoadRequest:
    """
    Optional inputs for a configuration loader.

    Implementations may use these to control where configuration is read from.
    """

    yaml_path: str = "data/config/config.yaml"
    env_prefix: str = "APP__"
    dotenv_path: Optional[str] = ".env"
