import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from html import escape
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel, Field

from . import config
from .browser import BrowserManager
from .chatgpt import ChatGPT

browser = BrowserManager()
chat_lock = asyncio.Lock()


class CommandParameter(BaseModel):
    """Describe a parameter that the frontend allows the AI to provide."""

    name: str
    type: str
    description: str
    required: bool = True


class AssistantCommand(BaseModel):
    """Describe an AI-visible command used for command validation."""

    id: str
    name: str
    description: str
    parameters: list[CommandParameter] = Field(default_factory=list)
    confirmation_required: bool = False


class ChatRequest(BaseModel):
    """
    The frontend constructs the complete AI message.

    The backend does not add instructions to the message.
    """

    message: str
    commands: list[AssistantCommand] = Field(default_factory=list)


def parse_ai_response(
    response: str,
) -> dict[str, Any]:
    """
    Parse a completed AI response.

    Supported formats:

    TEXT
    Hello.

    COMMAND
    {"command":"example","arguments":{}}

    Plain text is accepted as a normal text response.
    """

    text = response.strip()

    if not text:
        raise ValueError("ChatGPT returned an empty response.")

    if text.startswith("```"):
        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    if text.startswith("TEXT"):
        content = text[len("TEXT") :].strip()

        if not content:
            raise ValueError("TEXT response is empty.")

        return {
            "type": "text",
            "content": content,
        }

    if text.startswith("COMMAND"):
        payload = text[len("COMMAND") :].strip()

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("COMMAND response contains invalid JSON.") from exc

        if not isinstance(parsed, dict):
            raise TypeError("COMMAND response must be a JSON object.")

        command_id = parsed.get("command")

        if not isinstance(command_id, str):
            raise TypeError("COMMAND response must contain a string command ID.")

        arguments = parsed.get(
            "arguments",
            {},
        )

        if not isinstance(arguments, dict):
            raise TypeError("Command arguments must be an object.")

        return {
            "type": "command",
            "command": command_id,
            "arguments": arguments,
        }

    return {
        "type": "text",
        "content": text,
    }


def validate_ai_command(
    response: dict[str, Any],
    commands: list[AssistantCommand],
) -> dict[str, Any]:
    """Validate a command against the command catalog supplied by Android."""

    command_id = response.get("command")

    command = next(
        (item for item in commands if item.id == command_id),
        None,
    )

    if command is None:
        raise ValueError(f"AI requested unavailable command: {command_id}")

    arguments = response.get(
        "arguments",
        {},
    )

    if not isinstance(arguments, dict):
        raise TypeError("Command arguments must be an object.")

    parameter_map = {parameter.name: parameter for parameter in command.parameters}

    for argument_name in arguments:
        if argument_name not in parameter_map:
            raise ValueError(f"AI supplied unknown parameter: {argument_name}")

    for parameter in command.parameters:
        if parameter.required and parameter.name not in arguments:
            raise ValueError(f"AI omitted required parameter: {parameter.name}")

    for argument_name, value in arguments.items():
        parameter = parameter_map[argument_name]
        parameter_type = parameter.type.lower()

        if parameter_type == "text":
            if not isinstance(value, str):
                raise TypeError(f"Parameter '{argument_name}' must be text.")

        elif parameter_type == "number":
            if isinstance(value, bool):
                raise TypeError(f"Parameter '{argument_name}' must be a number.")

            if not isinstance(
                value,
                (int, float),
            ):
                raise TypeError(f"Parameter '{argument_name}' must be a number.")

        elif parameter_type == "boolean":
            if not isinstance(value, bool):
                raise TypeError(f"Parameter '{argument_name}' must be boolean.")

        else:
            raise ValueError(f"Unsupported parameter type: {parameter.type}")

    return {
        "type": "command",
        "command": command.id,
        "arguments": arguments,
    }


def detect_response_mode(
    buffer: str,
) -> str | None:
    """
    Detect the response mode.

    Returns:

    text
    command
    plain
    None

    None means that the buffer is still a possible partial
    TEXT or COMMAND prefix.
    """

    normalized = buffer.lstrip()

    if not normalized:
        return None

    text_prefix = "TEXT"
    command_prefix = "COMMAND"

    if normalized.startswith(text_prefix):
        suffix = normalized[len(text_prefix) :]

        if not suffix or suffix[0].isspace():
            return "text"

    if normalized.startswith(command_prefix):
        suffix = normalized[len(command_prefix) :]

        if not suffix or suffix[0].isspace():
            return "command"

    if text_prefix.startswith(normalized):
        return None

    if command_prefix.startswith(normalized):
        return None

    if len(normalized) < len(text_prefix):
        return None

    return "plain"


async def process_chat(
    chatgpt: ChatGPT,
    message: str,
) -> str:
    """Process a complete chat request."""

    async with chat_lock:
        return (await chatgpt.ask(message)).strip()


async def process_chat_stream(
    chatgpt: ChatGPT,
    message: str,
) -> AsyncIterator[str]:
    """Process a streaming chat request."""

    async with chat_lock:
        async for chunk in chatgpt.ask_stream(message):
            if chunk:
                yield chunk


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    """Initialize and shut down the browser."""

    page = await browser.start()

    chatgpt = ChatGPT(page)

    await chatgpt.initialize_page()

    if config.INTERNAL_CONTEXT:
        await chatgpt.initialize_context()

    elif config.CHAT_ID:
        print(
            "Using existing ChatGPT conversation as context.",
            flush=True,
        )

    else:
        print(
            "WARNING: No internal context configured.",
            flush=True,
        )

        print(
            "Using the currently opened ChatGPT conversation as context.",
            flush=True,
        )

    app.state.chatgpt = chatgpt

    yield

    await browser.stop()


app = FastAPI(
    title="Free API ChatGPT",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Return the current API health status."""

    chatgpt = getattr(
        app.state,
        "chatgpt",
        None,
    )

    if chatgpt is None:
        return {
            "status": "starting",
        }

    return {
        "status": "ok",
    }


@app.post("/chat")
async def chat(
    request: ChatRequest,
):
    """
    Return a complete assistant response.

    The frontend provides the complete AI prompt.
    """

    message = request.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    chatgpt = getattr(
        app.state,
        "chatgpt",
        None,
    )

    if chatgpt is None:
        raise HTTPException(
            status_code=503,
            detail="ChatGPT is not initialized.",
        )

    try:
        response = await process_chat(
            chatgpt,
            message,
        )

        parsed = parse_ai_response(response)

        if parsed["type"] == "command":
            parsed = validate_ai_command(
                parsed,
                request.commands,
            )

        return parsed

    except (
        PlaywrightTimeoutError,
        TimeoutError,
    ) as exc:
        raise HTTPException(
            status_code=504,
            detail=str(exc),
        ) from exc

    except (
        RuntimeError,
        ValueError,
        TypeError,
    ) as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
):
    """
    Stream an assistant response using Server-Sent Events.

    Normal text is streamed immediately.

    COMMAND responses are buffered until the complete JSON payload
    is available and then validated before being emitted.
    """

    message = request.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    chatgpt = getattr(
        app.state,
        "chatgpt",
        None,
    )

    if chatgpt is None:
        raise HTTPException(
            status_code=503,
            detail="ChatGPT is not initialized.",
        )

    async def generate():
        """Generate Server-Sent Events."""

        buffer = ""
        mode: str | None = None

        try:
            async for chunk in process_chat_stream(
                chatgpt,
                message,
            ):
                if not chunk:
                    continue

                if mode is None:
                    buffer += chunk

                    detected_mode = detect_response_mode(buffer)

                    if detected_mode is None:
                        continue

                    mode = detected_mode

                    if mode == "text":
                        normalized = buffer.lstrip()
                        content = normalized[len("TEXT") :]

                        if content:
                            yield (
                                "data: "
                                + json.dumps(
                                    {
                                        "type": "text_delta",
                                        "content": content,
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n\n"
                            )

                        buffer = ""

                        continue

                    if mode == "command":
                        normalized = buffer.lstrip()
                        buffer = normalized[len("COMMAND") :]

                        continue

                    if mode == "plain":
                        yield (
                            "data: "
                            + json.dumps(
                                {
                                    "type": "text_delta",
                                    "content": buffer,
                                },
                                ensure_ascii=False,
                            )
                            + "\n\n"
                        )

                        buffer = ""

                        continue

                elif mode == "text" or mode == "plain":
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "type": "text_delta",
                                "content": chunk,
                            },
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )

                elif mode == "command":
                    buffer += chunk

            if mode == "command":
                parsed = parse_ai_response("COMMAND " + buffer)

                parsed = validate_ai_command(
                    parsed,
                    request.commands,
                )

                payload = json.dumps(
                    parsed,
                    ensure_ascii=False,
                )

                yield (f"data: {payload}\n\n")

            elif mode == "text" or mode == "plain":
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "text_complete",
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )

            elif buffer.strip():
                parsed = parse_ai_response(buffer)

                if parsed["type"] == "command":
                    parsed = validate_ai_command(
                        parsed,
                        request.commands,
                    )

                payload = json.dumps(
                    parsed,
                    ensure_ascii=False,
                )

                yield (f"data: {payload}\n\n")

            yield "data: [DONE]\n\n"

        except (
            PlaywrightTimeoutError,
            TimeoutError,
        ) as exc:
            payload = json.dumps(
                {
                    "type": "error",
                    "message": (
                        "The assistant timed out while processing the request."
                    ),
                    "error_type": "timeout",
                },
                ensure_ascii=False,
            )

            yield f"data: {payload}\n\n"
            yield "data: [DONE]\n\n"

            print(
                f"ChatGPT timeout: {exc}",
                flush=True,
            )

        except (
            RuntimeError,
            ValueError,
            TypeError,
        ) as exc:
            payload = json.dumps(
                {
                    "type": "error",
                    "message": str(exc),
                    "error_type": "application",
                },
                ensure_ascii=False,
            )

            yield f"data: {payload}\n\n"
            yield "data: [DONE]\n\n"

            print(
                f"ChatGPT application error: {exc}",
                flush=True,
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def format_value(
    value,
) -> str:
    """Format a value for HTML output."""

    if value is None:
        return "<span class='null'>NULL</span>"

    if isinstance(
        value,
        (dict, list),
    ):
        value = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )

    text = str(value)

    try:
        parsed = json.loads(text)
    except (
        json.JSONDecodeError,
        TypeError,
    ):
        parsed = None

    if isinstance(
        parsed,
        (dict, list),
    ):
        text = json.dumps(
            parsed,
            ensure_ascii=False,
            indent=2,
        )

    return escape(text)
