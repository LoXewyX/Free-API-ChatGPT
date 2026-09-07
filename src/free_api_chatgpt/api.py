import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from html import escape

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel

from . import config
from .browser import BrowserManager
from .chatgpt import ChatGPT

browser = BrowserManager()
chat_lock = asyncio.Lock()


class ChatRequest(BaseModel):
    message: str


def extract_header_body(
    response: str,
) -> tuple[dict, str]:
    """Extract the HEADER JSON and BODY from a response."""
    header_marker = "HEADER"
    body_marker = "BODY"

    header_start = response.find(header_marker)

    if header_start == -1:
        raise ValueError("ChatGPT response does not contain HEADER.")

    body_start = response.find(
        body_marker,
        header_start + len(header_marker),
    )

    if body_start == -1:
        raise ValueError("ChatGPT response does not contain BODY.")

    header_text = response[header_start + len(header_marker) : body_start].strip()

    body = response[body_start + len(body_marker) :].strip()

    header = json.loads(header_text)

    if not isinstance(
        header,
        dict,
    ):
        raise TypeError("HEADER must contain a JSON object.")

    actions = header.get("actions")

    if not isinstance(
        actions,
        list,
    ):
        raise TypeError("HEADER must contain an actions array.")

    return header, body


async def process_chat(
    chatgpt: ChatGPT,
    message: str,
) -> str:
    """Process a normal chat request."""
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
    """Return API health status."""
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
    """Return a complete ChatGPT response."""
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

        return {
            "response": response,
        }

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
    """Stream a ChatGPT response using Server-Sent Events."""
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
        try:
            async for chunk in process_chat_stream(
                chatgpt,
                message,
            ):
                if not chunk:
                    continue

                payload = json.dumps(
                    chunk,
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
                    "error": str(exc),
                    "type": "timeout",
                },
                ensure_ascii=False,
            )

            yield (f"data: {payload}\n\n")
            yield "data: [DONE]\n\n"

        except (
            RuntimeError,
            ValueError,
            TypeError,
        ) as exc:
            payload = json.dumps(
                {
                    "error": str(exc),
                    "type": "application",
                },
                ensure_ascii=False,
            )

            yield (f"data: {payload}\n\n")
            yield "data: [DONE]\n\n"

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
