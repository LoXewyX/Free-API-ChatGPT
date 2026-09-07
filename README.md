# Free API ChatGPT

A local HTTP API for interacting with ChatGPT through browser automation.

**Free API ChatGPT** uses a persistent Firefox browser session controlled by Playwright to interact with ChatGPT. It exposes a local API through FastAPI, allowing compatible clients to use ChatGPT without an OpenAI API key.

## Features

* Browser-based ChatGPT access through Playwright and Firefox
* No OpenAI API key required
* Persistent Firefox profile and session
* FastAPI HTTP API
* Standard request/response chat endpoint
* Server-Sent Events (SSE) streaming endpoint
* Configurable:

  * Host and port
  * Firefox profile directory
  * ChatGPT conversation ID
  * Internal context
  * Headless/headful browser mode

## Requirements

You **do not need to install Python manually**. `uv` manages the Python environment and dependencies for the project.

You need:

* Python 3.12+
* `uv` 0.12+
* Firefox installed through Playwright
* A logged-in ChatGPT account/session available to the persistent Firefox profile

Check your `uv` version:

```bash
uv --version
```

## Installation

Clone the repository and install the dependencies:

```bash
git clone https://github.com/LoXewyX/Free-API-ChatGPT.git
cd Free-API-ChatGPT

uv venv
source .venv/bin/activate
uv sync

uv run playwright install firefox
```

### Windows PowerShell

Activate the virtual environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Activating the virtual environment is optional. The application can also be run directly with `uv run`.

## ChatGPT Session

The application uses a persistent Firefox profile to keep your ChatGPT session between launches.

On the first run, open ChatGPT in the browser and log in to your account. The session will be stored in the configured profile directory.

By default, the profile is stored in:

```text
./chatgpt-profile
```

Do not delete this directory if you want to preserve your ChatGPT session.

## Context Configuration

You can provide an internal context that is sent to ChatGPT when the application starts.

If you use `--chat-id`, the application uses that existing ChatGPT conversation as the conversation context. In this mode, you should also provide `--context` if you want to initialize additional internal context.

Example:

```bash
uv run python -m free_api_chatgpt --chat-id YOUR_CHAT_ID --context "Your internal context"
```

If you do not provide `--chat-id`, the application can start from the normal ChatGPT page and initialize the configured internal context.

## API Endpoints

| Method | Endpoint       | Description                                       |
| ------ | -------------- | ------------------------------------------------- |
| `GET`  | `/health`      | Returns the API and ChatGPT session status        |
| `POST` | `/chat`        | Sends a prompt and returns the complete response  |
| `POST` | `/chat/stream` | Sends a prompt and streams the response using SSE |

### `GET /health`

Check whether the API is running and the ChatGPT browser session is initialized.

### `POST /chat`

Send a prompt and wait for the complete ChatGPT response.

### `POST /chat/stream`

Send a prompt and receive the response incrementally using **Server-Sent Events (SSE)**.

## Running the API

The application can be started with `uv run`:

```bash
uv run python -m free_api_chatgpt
```

Configuration options can be passed through the application's command-line arguments.

For available options:

```bash
uv run python -m free_api_chatgpt --help
```

## Configuration

The application supports configuration for:

* `host` — HTTP server host
* `port` — HTTP server port
* `profile-dir` — persistent Firefox profile directory
* `chat-id` — existing ChatGPT conversation ID
* `context` — internal context sent during initialization
* `headless` — whether Firefox runs without a visible window

This makes it possible to run the API locally while keeping the ChatGPT browser session persistent across restarts.
