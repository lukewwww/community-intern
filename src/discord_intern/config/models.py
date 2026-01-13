from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from discord_intern.ai.interfaces import AIConfig


@dataclass(frozen=True, slots=True)
class AppSettings:
    dry_run: bool


@dataclass(frozen=True, slots=True)
class FileRotationSettings:
    """
    Date-based rotation settings (daily).

    This maps cleanly to Python's standard library TimedRotatingFileHandler behavior.
    """

    backup_count: int


@dataclass(frozen=True, slots=True)
class FileLoggingSettings:
    path: str
    rotation: FileRotationSettings


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str
    file: FileLoggingSettings


@dataclass(frozen=True, slots=True)
class DiscordSettings:
    token: str
    monitored_channel_ids: Sequence[str]
    ai_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class KnowledgeBaseSettings:
    sources_dir: str
    index_path: str

    web_fetch_timeout_seconds: float
    web_fetch_cache_dir: str

    max_source_bytes: int
    max_snippet_chars: int
    max_snippets_per_query: int
    max_sources_per_query: int


@dataclass(frozen=True, slots=True)
class AppConfig:
    """
    Effective runtime configuration after applying all precedence rules.

    This is a schema contract only. Loading, validation, and override resolution are not
    implemented at this stage.
    """

    app: AppSettings
    logging: LoggingSettings
    discord: DiscordSettings
    ai: AIConfig
    kb: KnowledgeBaseSettings


@dataclass(frozen=True, slots=True)
class ConfigLoadRequest:
    """
    Optional inputs for a configuration loader.

    Implementations may use these to control where configuration is read from.
    """

    yaml_path: str = "config.yaml"
    env_prefix: str = "APP__"
    dotenv_path: Optional[str] = ".env"
