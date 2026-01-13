# Configuration Specification (YAML + .env Overrides)

## Goal

All runtime configuration is read from a single YAML file (`config.yaml`). Environment variables override YAML values. A `.env` file is loaded (if present) to populate environment variables.

This specification defines:
- The required configuration file locations
- The full configuration schema
- The override precedence rules
- The environment-variable-to-YAML key mapping rules

## Files and precedence

The application loads configuration in this exact order (later wins):

1. Built-in defaults (hardcoded in code)
2. `config.yaml`
3. `.env` (if present), loaded into the process environment
4. Process environment variables

The final merged configuration MUST be validated against the Pydantic schema in `src/discord_intern/config/models.py`. Unknown keys MUST fail validation.

## Environment variable override mapping

Any environment variable whose name starts with `APP__` overrides a YAML key.

Mapping rules:

- Strip the `APP__` prefix.
- Split the remainder by double underscores (`__`) into path segments.
- Lowercase each segment.
- Join segments with dots to form the YAML path.

Example mappings:

- `APP__DISCORD__TOKEN` -> `discord.token`
- `APP__AI__REQUEST_TIMEOUT_SECONDS` -> `ai.request_timeout_seconds`
- `APP__KB__SOURCES_DIR` -> `kb.sources_dir`

## Environment variable value parsing

If a `.env` file is present, it MUST be loaded into the process environment using `python-dotenv` before applying environment variable overrides.

Environment variable override values MUST be read from the process environment as strings. The application MUST NOT perform additional parsing or type coercion.

Any non-string configuration values, including lists and objects, MUST be provided via `config.yaml`.

## Configuration schema

See the example config file: `examples/config.yaml`.

Related contract types:

- `src/discord_intern/ai/interfaces.py` (`AIConfig`)
- `src/discord_intern/config/models.py` (`AppConfig`, `DiscordSettings`, `KnowledgeBaseSettings`)
