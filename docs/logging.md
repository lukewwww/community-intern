# Logging

## Goal

The application MUST provide consistent, configurable logging across all modules (Discord adapter, AI, and knowledge base).

## What to log

- The application MUST log IDs and routing context: message IDs, channel IDs, thread IDs, and guild IDs (when present).
- The application MUST log decisions and outcomes: `should_reply`, gating results, selected knowledge sources, and citation source IDs.
- The application MUST log operational metadata: timeouts, retries, external call durations, and cache hits/misses.

## Runtime configuration

Logging MUST be configured via the `logging` section in `config.yaml`.

### Keys

- `logging.level` (string): The minimum log level (for example, `DEBUG`, `INFO`, `WARNING`, `ERROR`).
- `logging.file.path` (string): The log file path. If empty, file logging is disabled.
- `logging.file.rotation.backup_count` (int): Number of rotated log files to retain.

## Handlers and rotation

- The application MUST use Python's standard library `logging` module.
- The application MUST always configure `logging.StreamHandler` (console logging is always enabled).
- If `logging.file.path` is not empty, the application MUST configure `logging.handlers.TimedRotatingFileHandler` using:
  - `logging.file.path`
  - `when="midnight"` and `interval=1` (daily rotation)
  - `logging.file.rotation.backup_count` as `backupCount`
- Rotated files MUST be split by date (daily) and MUST include the date in the rotated filename (for example, `community-intern.log.2026-01-12`).
- If file logging is enabled and the file handler fails to initialize, the application MUST continue with console logging and MUST emit an error log describing the failure.

## Formatting and structure

- All handlers MUST use the same formatter.
- The formatter MUST include timestamp, level, logger name, and message.
- Log messages MUST be stable and machine-parsable.

## Implementation requirements

- Logging MUST be initialized once at startup, before any module does work.
- Logging initialization failures MUST NOT be silently ignored.



