from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from discord_intern.config.models import (
    AppConfig,
    ConfigLoadRequest,
)


def _deep_merge_dicts(base: MutableMapping[str, Any], override: Mapping[str, Any]) -> None:
    for k, v in override.items():
        if isinstance(v, Mapping) and isinstance(base.get(k), Mapping):
            _deep_merge_dicts(base[k], v)  # type: ignore[index]
            continue
        base[k] = v


def _read_yaml_config(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError as e:  # pragma: no cover
        raise ModuleNotFoundError(
            "Missing dependency: PyYAML is required to load the YAML config file. Install 'PyYAML'."
        ) from e

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Top-level YAML must be a mapping, got: {type(data).__name__}")
    return data


def _load_dotenv_if_present(dotenv_path: Path) -> None:
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
    except ModuleNotFoundError as e:  # pragma: no cover
        raise ModuleNotFoundError(
            "Missing dependency: python-dotenv is required to load .env. Install 'python-dotenv'."
        ) from e

    if not dotenv_path.exists():
        return
    load_dotenv(dotenv_path=dotenv_path, override=False)


def _env_var_name_to_segments(env_var_name: str, prefix: str) -> Sequence[str]:
    remainder = env_var_name[len(prefix) :]
    parts = [p for p in remainder.split("__") if p]
    if not parts:
        raise ValueError(f"Invalid environment variable override name: {env_var_name}")
    return [p.lower() for p in parts]


def _get_parent_mapping(config: MutableMapping[str, Any], path: Sequence[str]) -> MutableMapping[str, Any]:
    cur: MutableMapping[str, Any] = config
    for segment in path[:-1]:
        if segment not in cur:
            dotted = ".".join(path)
            raise KeyError(f"Unknown configuration key path: {dotted}")
        next_value = cur[segment]
        if not isinstance(next_value, dict):
            dotted = ".".join(path)
            raise TypeError(f"Configuration key path does not point to a mapping: {dotted}")
        cur = next_value
    return cur


def _apply_env_overrides(config: MutableMapping[str, Any], env_prefix: str) -> None:
    for name, value in os.environ.items():
        if not name.startswith(env_prefix):
            continue

        segments = _env_var_name_to_segments(name, env_prefix)
        parent = _get_parent_mapping(config, segments)
        leaf = segments[-1]
        dotted = ".".join(segments)

        if leaf not in parent:
            raise KeyError(f"Unknown configuration key path: {dotted}")
        existing = parent[leaf]
        if not isinstance(existing, str):
            raise TypeError(
                f"Environment variable overrides are only allowed for string values. "
                f"Key '{dotted}' is {type(existing).__name__}."
            )
        parent[leaf] = value


class YamlConfigLoader:
    async def load(self, request: ConfigLoadRequest = ConfigLoadRequest()) -> AppConfig:
        config: dict[str, Any] = copy.deepcopy(AppConfig().model_dump(mode="python"))

        yaml_path = Path(request.yaml_path)
        yaml_config = _read_yaml_config(yaml_path)
        _deep_merge_dicts(config, yaml_config)

        if request.dotenv_path is not None:
            _load_dotenv_if_present(Path(request.dotenv_path))

        _apply_env_overrides(config, request.env_prefix)
        return AppConfig.model_validate(config)
