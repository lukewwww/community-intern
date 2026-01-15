## Overview

This project is a LLM powered Discord FAQ bot that automatically monitors one or more Discord channels, detects user questions, and generates high-quality answers using a configured set of documentation sources such as local text files and web links.

When the system decides to respond, it creates a new Discord thread and posts the answer inside the thread. If new messages arrive in a thread that the bot has already answered, the bot sends the full thread context back to the AI module to produce a follow-up answer.

For the AI module, there is no separate "single message" input type: every call receives a `Conversation` that represents a thread context. A new channel message is modeled as a thread context containing exactly one message.

## Library targets

- **discord.py**: 2.6.4
- **langgraph**: 1.0.5
- **langchain-openai**: 1.1.7
- **langchain-core**: 1.2.7

Primary documentation entry points:

- **discord.py docs**: `https://discordpy.readthedocs.io/en/stable/`
- **LangGraph docs overview**: `https://docs.langchain.com/oss/python/langgraph/overview`
- **LangGraph API reference**: `https://reference.langchain.com/python/langgraph/`
  - Note: The official LangGraph docs are hosted under the LangChain OSS documentation domain.
- **LangChain OpenAI docs**: `https://python.langchain.com/docs/integrations/chat/openai/`

## Goals and non-goals

- **Goals**
  - Monitor all Discord channels the bot can read based on Discord permissions and respond to FAQ-like questions using knowledge base as context.
  - Create responses in **threads**, keeping the main channel clean.
  - Keep the AI module **stateless**: it must not persist chat history; conversation context is provided by the Bot Integration module.
  - Support a knowledge base made of:
    - Local text files in a folder
    - Web pages fetched from links stored in files (fetched via headless browser to support dynamic content)
  - Build a lightweight index at startup to help select the right sources quickly.
  - Make the AI module interface reusable so other platforms such as Telegram can be added later.

- **Non-goals**
  - Full conversational memory across threads beyond what the bot sends each call.
  - Moderation, user management, or advanced analytics.

## High-level architecture

The system is split into three modules:

1. **Bot Integration**, Discord adapter
2. **AI Response**, stateless decision and answer generation
3. **Knowledge Base**, content ingestion, startup indexing, and source loading

### Data flow, happy path

- A message is posted in a channel the bot can read.
- The Bot Integration module packages the message into a thread context as a `Conversation` with exactly one message and calls the AI module.
- The AI module decides whether to respond.
  - If **no**, the bot does nothing.
  - If **yes**, the bot creates a thread and posts the AI answer.
- If the thread receives a new message later, the bot gathers the full thread message list and calls the AI module again for a follow-up answer.

## Module 1: Bot Integration

### Responsibilities

- Connect to Discord and subscribe to events for all readable channels.
- Normalize Discord messages and threads into a platform-neutral format for the AI module.
- This module decides how to package Discord events into a thread context before calling the AI module:
  - **New channel message** -> call AI module with a thread containing exactly one message
  - **Thread update**, thread previously answered by bot -> call AI module with the full thread message list
- Create threads and post responses.

### Interfaces

- Bot-to-AI boundary: `src/community_intern/ai/interfaces.py` `AIClient`
- Shared models and result schema: `src/community_intern/core/models.py`

Implementation details for the Bot Integration module live in [`./module-bot-integration.md`](./module-bot-integration.md).

## Module 2: AI Response

### Responsibilities

- Accept conversation context from integration modules such as Discord and future platforms.
- Use an LLM call with a configured gating prompt to decide whether a response is needed.
- If a response is needed, use an LLM call to select relevant sources from the Knowledge Base index, load the selected source content, and use an LLM call to generate the answer.
- Validate answer quality with a separate LLM verification call and only return answers that are "good enough" to send publicly.
- When selected sources include URL identifiers, include those URLs in the final reply text to make it easy for users to open the primary references.
- Return a result in a strict schema to keep integrations simple.

### Statelessness requirement

The AI module **must not store chat history**. Any required context is provided in the `Conversation` payload for each call.

### Workflow

The AI module is implemented as a small LangGraph state graph:

1. Question gating
2. Source selection using KB index
3. Load selected source content
4. Answer generation
5. Answer verification

Full workflow and node specifications are defined in [`./module-ai-response.md`](./module-ai-response.md).

## Module 3: Knowledge Base

### Responsibilities

- Ingest content from:
  - A folder of local text files
  - Links referenced inside those files, HTTP and HTTPS (fetched dynamically via headless browser)
- On each startup:
  - Build a lightweight index to help select the right sources
- Provide retrieval helpers to the AI module:
  - Provide index text and load source content for selected identifiers

Contracts and examples:

- Knowledge base interface contracts: `src/community_intern/kb/interfaces.py`
- Example index artifact: `examples/kb_index.txt`
Details: [`./module-knowledge-base.md`](./module-knowledge-base.md).

## Observability and safety

- **Logging**
  - Use structured logging and avoid storing private message content long-term.
  - See [`./logging.md`](./logging.md).

- **Config**
  - Load settings from `config.yaml` with environment-variable overrides.
  - See [`./configuration.md`](./configuration.md) and `src/community_intern/config/models.py`.

## Extensibility

To add a new platform such as Telegram, implement a new integration module that:

- Converts platform events into the shared `Conversation` model
- Calls the AI module via the same `generate_reply` boundary
- Posts responses using the platform’s native reply/thread mechanism
