## Docker Deployment

## Run the Docker container using prebuilt image

### 1) Ensure the data directory is writable

Make sure `build/data` is writable so the container can create files and folders.

### 2) Create the .env file

Create `build/data/.env` and add your secrets.

```bash
$ cat <<'EOF' > build/data/.env
APP__DISCORD__TOKEN=your_discord_bot_token
APP__AI__LLM_BASE_URL=https://llm.provider/v1
APP__AI__LLM_API_KEY=your_llm_api_key
EOF
```

### 3) Initialize the Knowledge Base

Run the Knowledge Base index build using the Docker image.

```bash
$ docker compose run --rm community-intern python -m community_intern init_kb
```

### 4) Start the container

Start the container from the repository root.

```bash
$ docker compose up -d
```

## Build the image from source code

Build the image from the repository root.

```bash
$ docker build -f build/Dockerfile -t community-intern:local .
```
