# Discord Intern

Discord Intern is an AI and LLM powered Discord FAQ assistant that monitors selected channels, detects questions, and posts helpful answers in newly created threads to keep the main channel clean.

## What it does

- Watches configured Discord channels for question-like messages
- Uses AI to decide whether a message is a question and whether it is in scope to answer (and skips messages that are not)
- Uses an LLM to draft a helpful answer grounded in the knowledge base (local files and configured web sources) when it decides to respond
- Creates a thread from the triggering message and replies inside that thread
- Supports follow-up questions by replying again when a thread continues (using the full thread context)

## Key features


- **AI-generated, source-grounded answers**: An LLM generates answers from your documentation sources and can include citations back to those sources.
- **Knowledge base from files and links**: Uses a local folder of text sources and can incorporate relevant web pages referenced by links.
- **Bring your own LLM**: Choose which LLM provider and model to use via configuration.
- **Thread-first replies**: Answers live in message-backed threads rather than cluttering the channel.
- **Configurable scope**: Communities can tune what kinds of questions are considered answerable without changing code.

## Documentation

See `docs/` for architecture and module-level documentation, plus configuration guidance.
