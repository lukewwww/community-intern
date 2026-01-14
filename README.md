# Community Intern

Community Intern is an AI and LLM powered Discord FAQ assistant that monitors selected channels, detects questions, and posts helpful answers in newly created threads to keep the main channel clean.

## What it does

- Watches all readable Discord channels for question-like messages
- Uses AI to decide whether a message is a question and whether it is in scope to answer (and skips messages that are not)
- Uses an LLM to draft a helpful answer grounded in the knowledge base (local files and configured web sources) when it decides to respond
- Creates a thread from the triggering message and replies inside that thread
- Supports follow-up questions by replying again when a thread continues (using the full thread context)

## Key features


- **AI-generated, source-grounded answers**: An LLM generates answers from your documentation sources and can include citations back to those sources.
- **Knowledge base from files and links**: Uses a local folder of text sources and can incorporate relevant web pages referenced by links (supports dynamic content loading).
- **Bring your own LLM**: Choose which LLM provider and model to use via configuration.
- **Thread-first replies**: Answers live in message-backed threads rather than cluttering the channel.
- **Configurable scope**: Communities can tune what kinds of questions are considered answerable without changing code.

## Documentation

See `docs/` for architecture and module-level documentation, plus configuration guidance.

## Get Started

### 1) Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Create a Discord bot and enable message content intent

- Create an application + bot in the Discord Developer Portal.
- Enable **Message Content Intent** for the bot (required to read message text).
- Invite/install the bot to your server **without** requesting **View Channels** (and without **Administrator**). The bot should start with no channel visibility by default.
- After installation, Discord will create a role for the bot (for this project: **Community Intern**).
- To allow the bot to operate in a specific channel, grant the **Community Intern** role channel permissions:
  - **View Channel**
  - **Read Message History**
  - **Create Public Threads** (and/or **Create Private Threads**, depending on your usage)
  - **Send Messages in Threads**

### 3) Create `config.yaml`

Start from `examples/config.yaml` and copy it to `data/config/config.yaml`.

At minimum, set:

- `discord.token`: your bot token

Example:

```yaml
discord:
  token: "YOUR_BOT_TOKEN"
  ai_timeout_seconds: 30

app:
  dry_run: false
```

Notes:

- Environment variables can override string keys using the `APP__` prefix (see `docs/configuration.md`).
- Control which channels are monitored by granting (or denying) channel visibility for the **Community Intern** role on a per-channel (or per-category) basis.

### 4) Initialize Knowledge Base

Before running the bot, initialize the knowledge base index. This will scan your sources folder and fetch any web links.

```bash
python -m community_intern init_kb
```

### 5) Run the bot (mock AI mode)

This project currently ships with a mock AI client that always replies with a fixed message. This lets you validate Discord connectivity, routing, and thread creation before implementing the full AI module.

```bash
python -m community_intern run
```
