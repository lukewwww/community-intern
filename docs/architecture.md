## Overview

This project is a Discord FAQ bot that automatically monitors one or more Discord channels, detects user questions, and generates high-quality answers using a configured set of documentation sources (local text files and web links).

When the system decides to respond, it creates a new Discord thread and posts the answer inside the thread. If new messages arrive in a thread that the bot has already answered, the bot sends the full thread context back to the AI module to produce a follow-up answer.
For the AI module, there is no separate "single message" input type: every call receives a `Conversation` that represents a thread context. A new channel message is modeled as a thread context containing exactly one message.

## Library targets

- **discord.py**: 2.6.4 (PyPI)
- **langgraph**: 1.0.5 (PyPI)

Primary documentation entry points:

- **discord.py docs**: `https://discordpy.readthedocs.io/en/stable/`
- **LangGraph docs (overview)**: `https://docs.langchain.com/oss/python/langgraph/overview`
- **LangGraph API reference**: `https://reference.langchain.com/python/langgraph/`
  - Note: The official LangGraph docs are hosted under the LangChain OSS documentation domain; this does not imply the project uses the LangChain library.

## Goals and non-goals

- **Goals**
  - Monitor configured Discord channels and respond to FAQ-like questions with grounded answers.
  - Create responses in **threads**, keeping the main channel clean.
  - Keep the AI module **stateless**: it must not persist chat history; conversation context is provided by the bot adapter.
  - Support a knowledge base made of:
    - Local text files in a folder
    - Web pages fetched from links stored in files
  - Build a lightweight index at startup to route questions to the right sources quickly.
  - Make the AI module interface reusable so other platforms (e.g., Telegram) can be added later.

- **Non-goals**
  - Full conversational memory across threads (beyond what the bot sends each call).
  - Moderation, user management, or advanced analytics.

## High-level architecture

The system is split into three modules:

1. **Bot Integration (Discord adapter)**
2. **AI Response (stateless decision + answer generation)**
3. **Knowledge Base (content ingestion + startup indexing + retrieval)**

### Data flow (happy path)

- A message is posted in a monitored channel.
- The Discord adapter packages the message into a thread context (a `Conversation` with exactly one message) and calls the AI module.
- The AI module decides whether to respond.
  - If **no**, the adapter does nothing.
  - If **yes**, the adapter creates a thread and posts the AI answer.
- If the thread receives a new message later, the adapter gathers the full thread message list and calls the AI module again for a follow-up answer.

## Module 1: Bot Integration (Discord adapter)

### Responsibilities

- Connect to Discord and subscribe to events for configured channels.
- Normalize Discord messages and threads into a platform-neutral format for the AI module.
- Decide routing (adapter concern only; the AI module always receives a thread context):
  - **New channel message** -> call AI module with a thread containing exactly one message
  - **Thread update** (thread previously answered by bot) -> call AI module with the full thread message list
- Create threads and post responses.

### Interfaces

- Adapter-to-AI boundary: `src/discord_intern/ai/interfaces.py` (`AIClient`)
- Shared models and result schema: `src/discord_intern/core/models.py`

Implementation details for the Discord adapter live in `docs/module-bot-integration.md`.

## Module 2: AI Response (LangGraph)

### Responsibilities

- Accept conversation context from adapters (Discord now, others later).
- Decide whether a response is needed (config-driven; e.g., only answer questions about errors encountered when starting a node).
- If needed, retrieve relevant knowledge and generate a grounded answer.
- Validate answer quality with a lightweight second LLM check; only return answers that are "good enough" to send publicly.
- Return a result in a strict schema to keep adapters simple.

### Statelessness requirement

The AI module **must not store chat history**. Any required context is provided in the `Conversation` payload for each call.

### Workflow

The AI module is implemented as a small LangGraph state graph:

1. Question gating
2. Retrieval routing + retrieval (file/web/etc.)
3. Answer generation
4. Answer verification

Full workflow and node specifications are defined in `docs/module-ai-response.md`.

## Module 3: Knowledge Base

### Responsibilities

- Ingest content from:
  - A folder of local text files
  - Links referenced inside those files (HTTP/HTTPS)
- On each startup:
  - Build a lightweight index to route queries to the right sources
- Provide retrieval helpers to the AI module:
  - Given a query, select sources via the index and return relevant snippets for citations

Contracts and examples:

- Knowledge base interface contracts: `src/discord_intern/kb/interfaces.py`
- Example index artifact: `examples/kb_index.json`
Details: `docs/module-knowledge-base.md`.

## Observability and safety

- **Logging**
  - Use structured logging and avoid storing private message content long-term.
  - See `docs/logging.md`.

- **Config**
  - Load settings from `config.yaml` with environment-variable overrides.
  - See `docs/configuration.md` and `src/discord_intern/config/models.py`.

## Extensibility

To add a new platform (e.g., Telegram), implement a new adapter that:

- Converts platform events into the shared `Conversation` model
- Calls the AI module via the same `generate_reply(...)` boundary
- Posts responses using the platform’s native reply/thread mechanism
