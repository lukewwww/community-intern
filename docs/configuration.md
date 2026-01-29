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

1. `config.yaml`
2. `.env` (if present), loaded into the process environment
3. Process environment variables

The `config.yaml` file MUST contain all required configuration keys. The final merged configuration MUST be validated against the Pydantic schema in `src/community_intern/config/models.py`. Unknown keys MUST fail validation.

## Environment variable override mapping

Any environment variable whose name starts with `APP__` overrides a YAML key.

Mapping rules:

- Strip the `APP__` prefix.
- Split the remainder by double underscores (`__`) into path segments.
- Lowercase each segment.
- Join segments with dots to form the YAML path.

Example mappings:

- `APP__DISCORD__TOKEN` -> `discord.token`
- `APP__AI_RESPONSE__GRAPH_TIMEOUT_SECONDS` -> `ai_response.graph_timeout_seconds`
- `APP__AI_RESPONSE__LLM__API_KEY` -> `ai_response.llm.api_key`
- `APP__KB__SOURCES_DIR` -> `kb.sources_dir`

## Environment variable value parsing

If a `.env` file is present, it MUST be loaded into the process environment using `python-dotenv` before applying environment variable overrides.

Environment variable override values MUST be read from the process environment as strings. The application MUST NOT perform additional parsing or type coercion.

Any non-string configuration values, including lists and objects, MUST be provided via `config.yaml`.

## Configuration schema

See the example config file: `examples/config.yaml`.

Related contract types:

- `src/community_intern/ai_response/config.py` (`AIConfig`)
- `src/community_intern/config/models.py` (`AppConfig`, `DiscordSettings`, `KnowledgeBaseSettings`)

## AI Response structured output method

`ai_response.llm.structured_output_method` controls how the application enforces structured outputs when using `with_structured_output()`.

Allowed values:

- `json_schema`: Use the provider JSON schema structured output mechanism.
- `function_calling`: Force tool calling and parse the tool call arguments.

Use `function_calling` when the selected model does not support native JSON schema structured output.
