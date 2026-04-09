---
title: Ppt Agent Environment Server
emoji: 📣
colorFrom: red
colorTo: indigo
sdk: docker
pinned: false
app_port: 7860
base_path: /web
tags:
  - openenv
---

# Ppt Agent Environment

OpenEnv environment for building and grading PowerPoint presentations. The server hosts the benchmark tasks and graders, and the root `inference.py` connects to the running environment to generate decks with an OpenAI-compatible LLM endpoint.

## Submission Requirements

Set these environment variables before running either the environment or `inference.py`:

- `API_BASE_URL`: OpenAI-compatible API endpoint for model calls
- `MODEL_NAME`: model identifier for inference and environment-side judge calls
- `HF_TOKEN`: API token used by the OpenAI client

The repository is structured to match the benchmark contract:

- `inference.py` lives at the repo root
- `inference.py` uses `openai.OpenAI`
- the Dockerfile runs the environment server, not the inference script
- the environment serves `reset`, `step`, `state`, and schema endpoints through OpenEnv

## Quick Start

Start the environment locally:

```bash
uv run --env-file .env uvicorn server.app:app --host 0.0.0.0 --port 7860
```

Run the baseline inference script against the local environment:

```python
uv run --env-file .env python inference.py
```

`inference.py` emits structured logs in this format:

- `[START] task=<task_name> env=<benchmark> model=<model_name>`
- `[STEP] step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>`
- `[END] success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>`

## Building the Docker Image

Build from the repo root:

```bash
docker build -t ppt-agent-env:latest .
```

## Deploying to Hugging Face Spaces

This repo is configured as a Docker Space via `openenv.yaml` and the root `Dockerfile`.

Push with OpenEnv:

```bash
openenv push
```

In the Hugging Face Space settings, define these secrets or variables:

- `API_BASE_URL`
- `MODEL_NAME`
- `HF_TOKEN`

After deployment, the validator should be able to reach:

- `POST /reset`
- `POST /step`
- `GET /state`
- `GET /schema`
- `GET /health`

### Prerequisites

- Authenticate with Hugging Face before pushing
- Ensure the Space has enough outbound access for model API calls

### Options

- `--repo-id`, `-r`: target Space repository
- `--private`: create a private Space
- `--base-image`, `-b`: override the Docker base image if needed

### Examples

```bash
openenv push
openenv push --repo-id my-org/my-env
openenv push --private
```

The Space URL will be the ping target for `scripts/validate-submission.sh`.

## Environment Details

### Action

`PptAgentAction` supports these macro actions:

- `create_slide`
- `update_slide`
- `delete_slide`
- `save_presentation`

### Observation

`PptAgentObservation` includes:

- `task_name`
- `difficulty`
- `slide_count`
- `task_prompt`
- `source_context`
- `last_action_error`
- `score`
- `prompt_summary`
- `last_action_result`
- `termination_reason`
- `reward`
- `done`

### Reward

Intermediate steps receive bounded slide-level reward. Finalization evaluates the full presentation and returns a normalized score in `[0.0, 1.0]`.

## Tasks

The environment currently ships with 6 scenarios in `server/data.json`:

- 2 easy
- 2 medium
- 2 hard

Each task includes:

- a task prompt
- source-pack documents
- task constraints
- a grader-backed final reward

## Advanced Usage

### Connecting to an Existing Server

Connect the client directly to a running environment:

```python
from client import PptAgentEnv
from models import PptAgentAction

env = PptAgentEnv(base_url="http://localhost:7860")

result = env.reset(difficulty="easy")
result = env.step(PptAgentAction(action_type="save_presentation", payload={"path": "outputs/demo.pptx"}))
```

Calling `close()` disconnects the client but does not stop the remote server.

## Validation

Run the built-in checks before submission:

```bash
openenv validate
docker build .
./scripts/validate-submission.sh https://your-space.hf.space .
```

The validator checks:

- the HF Space is live and responds to `/reset`
- the Docker build succeeds
- `openenv validate` passes

## Running Locally

Start the server:

```bash
uv run --env-file .env uvicorn server.app:app --host 0.0.0.0 --port 7860
```

Run inference against it:

```bash
uv run --env-file .env python inference.py
```

You can set `TASK_DIFFICULTY=easy|medium|hard` to control which scenario bucket is sampled.

## Project Structure

```
ppt_agent/
├── .dockerignore         # Docker build exclusions
├── __init__.py            # Module exports
├── README.md              # This file
├── openenv.yaml           # OpenEnv manifest
├── pyproject.toml         # Project metadata and dependencies
├── uv.lock                # Locked dependencies (generated)
├── client.py              # PptAgentEnv client
├── models.py              # Action and Observation models
└── server/
    ├── __init__.py        # Server module exports
    ├── ppt_agent_environment.py  # Core environment logic
    ├── app.py             # FastAPI application (HTTP + WebSocket endpoints)
    └── Dockerfile         # Container image definition
```
