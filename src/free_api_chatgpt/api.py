import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from html import escape
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel

from .browser import BrowserManager
from .chatgpt import ChatGPT
from .config import (
    DB_ENABLED,
    INTERNAL_CONTEXT,
    NO_DB_INTERNAL_CONTEXT,
    get_local_timezone,
)
from .db import Database

database = Database()
browser = BrowserManager()


class ChatRequest(BaseModel):
    message: str


def database_context() -> str:
    return json.dumps(
        database.get_database_overview(),
        ensure_ascii=False,
    )


def build_internal_context() -> str:
    if not DB_ENABLED:
        return NO_DB_INTERNAL_CONTEXT

    return INTERNAL_CONTEXT + "\n\nCURRENT DATABASE STATE:\n" + database_context()


def local_to_utc(value: str) -> str:
    timezone = ZoneInfo(get_local_timezone())

    local_datetime = datetime.strptime(
        value,
        "%Y-%m-%d %H:%M:%S",
    ).replace(
        tzinfo=timezone,
    )

    utc_datetime = local_datetime.astimezone(UTC)

    return utc_datetime.strftime(
        "%Y-%m-%d %H:%M:%S",
    )


def extract_header_body(
    response: str,
) -> tuple[dict, str]:
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

    if not isinstance(header, dict):
        raise TypeError("HEADER must contain a JSON object.")

    actions = header.get("actions")

    if not isinstance(actions, list):
        raise TypeError("HEADER must contain an actions array.")

    return header, body


def execute_database_action(
    action: dict,
) -> dict:
    if not isinstance(action, dict):
        raise TypeError("Database action must be an object.")

    action_name = action.get("action")

    if action_name == "list_entries":
        category = action.get("category")
        limit = action.get("limit", 50)

        if category is not None and not isinstance(
            category,
            str,
        ):
            raise TypeError("category must be a string.")

        if not isinstance(limit, int):
            raise TypeError("limit must be an integer.")

        return {
            "action": action_name,
            "result": database.list_entries(
                category=category,
                limit=limit,
            ),
        }

    if action_name == "search_entries":
        query = action.get("query")
        limit = action.get("limit", 10)

        if not isinstance(query, str):
            raise TypeError("query must be a string.")

        if not isinstance(limit, int):
            raise TypeError("limit must be an integer.")

        return {
            "action": action_name,
            "result": database.search_entries(
                query=query,
                limit=limit,
            ),
        }

    if action_name == "get_entry":
        entry_id = action.get("entry_id")

        if not isinstance(entry_id, int):
            raise TypeError("entry_id must be an integer.")

        return {
            "action": action_name,
            "result": database.get_entry(
                entry_id,
            ),
        }

    if action_name == "create_entry":
        key = action.get("key")
        title = action.get("title")
        category = action.get("category")
        data = action.get("data")

        if not isinstance(key, str):
            raise TypeError("key must be a string.")

        if not isinstance(title, str):
            raise TypeError("title must be a string.")

        if not isinstance(category, str):
            raise TypeError("category must be a string.")

        if not isinstance(data, dict):
            raise TypeError("data must be an object.")

        entry = database.create_entry(
            key=key,
            title=title,
            category=category,
            data=data,
        )

        return {
            "action": action_name,
            "result": entry,
        }

    if action_name == "update_entry":
        entry_id = action.get("entry_id")
        title = action.get("title")
        category = action.get("category")
        data = action.get("data")

        if not isinstance(entry_id, int):
            raise TypeError("entry_id must be an integer.")

        if title is not None and not isinstance(
            title,
            str,
        ):
            raise TypeError("title must be a string.")

        if category is not None and not isinstance(
            category,
            str,
        ):
            raise TypeError("category must be a string.")

        if data is not None and not isinstance(
            data,
            dict,
        ):
            raise TypeError("data must be an object.")

        entry = database.update_entry(
            entry_id=entry_id,
            title=title,
            category=category,
            data=data,
        )

        return {
            "action": action_name,
            "result": entry,
        }

    if action_name == "delete_entry":
        entry_id = action.get("entry_id")

        if not isinstance(entry_id, int):
            raise TypeError("entry_id must be an integer.")

        return {
            "action": action_name,
            "result": database.delete_entry(
                entry_id,
            ),
        }

    if action_name == "list_history":
        entry_id = action.get("entry_id")
        action_filter = action.get("action_filter")
        created_after = action.get("created_after")
        created_before = action.get("created_before")
        limit = action.get("limit", 50)

        if entry_id is not None and not isinstance(
            entry_id,
            int,
        ):
            raise TypeError("entry_id must be an integer.")

        if action_filter is not None and not isinstance(
            action_filter,
            str,
        ):
            raise TypeError("action_filter must be a string.")

        if created_after is not None and not isinstance(
            created_after,
            str,
        ):
            raise TypeError("created_after must be a string.")

        if created_before is not None and not isinstance(
            created_before,
            str,
        ):
            raise TypeError("created_before must be a string.")

        if not isinstance(limit, int):
            raise TypeError("limit must be an integer.")

        if created_after is not None:
            created_after = local_to_utc(
                created_after,
            )

        if created_before is not None:
            created_before = local_to_utc(
                created_before,
            )

        print(
            "HISTORY LOCAL → UTC:",
            created_after,
            "→",
            created_before,
        )

        return {
            "action": action_name,
            "result": database.list_history(
                entry_id=entry_id,
                action=action_filter,
                created_after=created_after,
                created_before=created_before,
                limit=limit,
            ),
        }

    if action_name == "get_history":
        history_id = action.get("history_id")

        if not isinstance(history_id, int):
            raise TypeError("history_id must be an integer.")

        return {
            "action": action_name,
            "result": database.get_history(
                history_id,
            ),
        }

    if action_name == "update_history":
        history_id = action.get("history_id")
        title = action.get("title")
        category = action.get("category")
        data = action.get("data")
        message = action.get("message")
        response = action.get("response")

        if not isinstance(history_id, int):
            raise TypeError("history_id must be an integer.")

        if title is not None and not isinstance(
            title,
            str,
        ):
            raise TypeError("title must be a string.")

        if category is not None and not isinstance(
            category,
            str,
        ):
            raise TypeError("category must be a string.")

        if data is not None and not isinstance(
            data,
            dict,
        ):
            raise TypeError("data must be an object.")

        if message is not None and not isinstance(
            message,
            str,
        ):
            raise TypeError("message must be a string.")

        if response is not None and not isinstance(
            response,
            str,
        ):
            raise TypeError("response must be a string.")

        history = database.update_history(
            history_id=history_id,
            title=title,
            category=category,
            data=data,
            message=message,
            response=response,
        )

        return {
            "action": action_name,
            "result": history,
        }

    if action_name == "delete_history":
        history_id = action.get("history_id")

        if not isinstance(history_id, int):
            raise TypeError("history_id must be an integer.")

        return {
            "action": action_name,
            "result": database.delete_history(
                history_id,
            ),
        }

    raise ValueError(f"Unsupported database action: {action_name}")


async def process_chat(
    chatgpt: ChatGPT,
    message: str,
) -> str:
    """
    NORMAL /chat path.

    IMPORTANT:
    This function NEVER calls ask_stream().
    """

    if not DB_ENABLED:
        return (await chatgpt.ask(message)).strip()

    prompt = message

    for round_number in range(10):
        response = await chatgpt.ask(prompt)

        print(f"\n--- DATABASE ROUND {round_number + 1} ---")
        print(response)
        print("--- END DATABASE ROUND ---\n")

        header, body = extract_header_body(
            response,
        )

        actions = header["actions"]

        print("DATABASE ACTIONS:")
        print(
            json.dumps(
                actions,
                ensure_ascii=False,
                indent=2,
            )
        )

        if not actions:
            database.log_interaction(
                message=message,
                response=body,
            )

            return body

        results = [execute_database_action(action) for action in actions]

        print("DATABASE RESULTS:")
        print(
            json.dumps(
                results,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        prompt = (
            "DATABASE ACTION RESULTS:\n"
            + json.dumps(
                results,
                ensure_ascii=False,
            )
            + "\n\n"
            "Use these results to answer the user's "
            "original request.\n"
            "Return exactly the required HEADER and "
            "BODY format."
        )

    raise RuntimeError("Maximum database action rounds exceeded.")


async def process_chat_stream(
    chatgpt: ChatGPT,
    message: str,
) -> AsyncIterator[str]:
    """
    /chat/stream path.

    IMPORTANT:
    This function is the ONLY normal application path
    that calls ask_stream().
    """

    if not DB_ENABLED:
        async for chunk in chatgpt.ask_stream(message):
            if chunk:
                yield chunk

        return

    prompt = message

    for round_number in range(10):
        parts: list[str] = []

        async for chunk in chatgpt.ask_stream(prompt):
            parts.append(chunk)

        response = "".join(parts).strip()

        print(f"\n--- STREAM DATABASE ROUND {round_number + 1} ---")
        print(response)
        print("--- END DATABASE ROUND ---\n")

        header, body = extract_header_body(
            response,
        )

        actions = header["actions"]

        print("DATABASE ACTIONS:")
        print(
            json.dumps(
                actions,
                ensure_ascii=False,
                indent=2,
            )
        )

        if not actions:
            database.log_interaction(
                message=message,
                response=body,
            )

            chunk_size = 40

            for index in range(
                0,
                len(body),
                chunk_size,
            ):
                yield body[index : index + chunk_size]

                await asyncio.sleep(0)

            return

        results = [execute_database_action(action) for action in actions]

        print("DATABASE RESULTS:")
        print(
            json.dumps(
                results,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        prompt = (
            "DATABASE ACTION RESULTS:\n"
            + json.dumps(
                results,
                ensure_ascii=False,
            )
            + "\n\n"
            "Use these results to answer the user's "
            "original request.\n"
            "Return exactly the required HEADER and "
            "BODY format."
        )

    raise RuntimeError("Maximum database action rounds exceeded.")


async def initialize_chatgpt_context(
    chatgpt: ChatGPT,
):
    await chatgpt.initialize_context(
        build_internal_context(),
    )


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    if DB_ENABLED:
        database.initialize()

    page = await browser.start()

    chatgpt = ChatGPT(page)

    await chatgpt.initialize_page()

    await initialize_chatgpt_context(chatgpt)

    app.state.chatgpt = chatgpt
    app.state.context_initialized = True

    yield

    await browser.stop()


app = FastAPI(
    title="Free API ChatGPT",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "context_initialized": getattr(
            app.state,
            "context_initialized",
            False,
        ),
    }


@app.post("/chat")
async def chat(
    request: ChatRequest,
):
    message = request.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    if not getattr(
        app.state,
        "context_initialized",
        False,
    ):
        raise HTTPException(
            status_code=503,
            detail="ChatGPT context is not initialized.",
        )

    try:
        response = await process_chat(
            app.state.chatgpt,
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
        sqlite3.Error,
    ) as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
):
    message = request.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    if not getattr(
        app.state,
        "context_initialized",
        False,
    ):
        raise HTTPException(
            status_code=503,
            detail="ChatGPT context is not initialized.",
        )

    async def generate():
        try:
            async for chunk in process_chat_stream(
                app.state.chatgpt,
                message,
            ):
                if not chunk:
                    continue

                yield (
                    "data: "
                    + json.dumps(
                        chunk,
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )

                await asyncio.sleep(0)

            yield "data: [DONE]\n\n"

        except (
            PlaywrightTimeoutError,
            TimeoutError,
        ) as exc:
            print(f"SSE timeout: {exc}")

            payload = json.dumps(
                {
                    "error": str(exc),
                    "type": "timeout",
                },
                ensure_ascii=False,
            )

            yield f"data: {payload}\n\n"
            yield "data: [DONE]\n\n"

        except (
            RuntimeError,
            ValueError,
            TypeError,
            sqlite3.Error,
        ) as exc:
            print(f"SSE application error: {exc}")

            payload = json.dumps(
                {
                    "error": str(exc),
                    "type": "application",
                },
                ensure_ascii=False,
            )

            yield f"data: {payload}\n\n"
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


def render_database_page(
    table_name: str | None = None,
    page: int = 1,
) -> str:
    overview = database.get_database_overview()
    tables = overview["table_stats"]

    if table_name is None:
        return render_database_index(
            overview,
            tables,
        )

    if not database.table_exists(table_name):
        raise HTTPException(
            status_code=404,
            detail="Table not found.",
        )

    page = max(1, page)

    limit = 50
    offset = (page - 1) * limit

    columns = database.get_table_info(
        table_name,
    )

    rows = database.get_table_rows(
        table_name,
        limit=limit,
        offset=offset,
    )

    total_rows = database.get_table_row_count(
        table_name,
    )

    pages = max(
        1,
        (total_rows + limit - 1) // limit,
    )

    column_names = [column["name"] for column in columns]

    header_html = "".join(f"<th>{escape(name)}</th>" for name in column_names)

    row_html = ""

    primary_key = next(
        (column["name"] for column in columns if column["primary_key"]),
        None,
    )

    for row in rows:
        cells = []

        for name in column_names:
            value = row[name]

            if primary_key is not None and name == primary_key:
                cells.append(
                    "<td>"
                    f"<a href='/db/"
                    f"{escape(table_name)}"
                    f"/row/{escape(str(value))}'>"
                    f"{format_value(value)}"
                    "</a>"
                    "</td>"
                )
            else:
                cells.append(f"<td>{format_value(value)}</td>")

        row_html += "<tr>" + "".join(cells) + "</tr>"

    previous_link = ""

    if page > 1:
        previous_link = (
            f"<a href='/db/{escape(table_name)}?page={page - 1}'>Previous</a>"
        )

    next_link = ""

    if page < pages:
        next_link = f"<a href='/db/{escape(table_name)}?page={page + 1}'>Next</a>"

    schema_rows = "".join(
        f"""
        <tr>
            <td>{escape(column["name"])}</td>
            <td>{escape(column["type"])}</td>
            <td>
                {"No" if column["notnull"] else "Yes"}
            </td>
            <td>
                {"Yes" if column["primary_key"] else "No"}
            </td>
            <td>
                {format_value(column["default"])}
            </td>
        </tr>
        """
        for column in columns
    )

    return database_html(
        f"""
        <a href="/db">← Database</a>

        <h1>{escape(table_name)}</h1>

        <p>
            {total_rows} rows · page {page} of {pages}
        </p>

        <div class="pagination">
            {previous_link}
            {next_link}
        </div>

        <h2>Schema</h2>

        <table>
            <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Nullable</th>
                <th>Primary key</th>
                <th>Default</th>
            </tr>

            {schema_rows}
        </table>

        <h2>Rows</h2>

        <table>
            <tr>{header_html}</tr>
            {row_html}
        </table>

        <div class="pagination">
            {previous_link}
            {next_link}
        </div>
        """
    )


def render_database_index(
    overview: dict,
    tables: list[dict],
) -> str:
    table_rows = ""

    for table in tables:
        name = table["name"]
        row_count = table["rows"]

        table_rows += (
            "<tr>"
            f"<td>"
            f"<a href='/db/{escape(name)}'>"
            f"{escape(name)}"
            f"</a>"
            f"</td>"
            f"<td>{row_count}</td>"
            "</tr>"
        )

    return database_html(
        f"""
        <h1>Database</h1>

        <div class="stats">
            <div>
                <strong>
                    {overview["tables"]}
                </strong>
                <span>tables</span>
            </div>

            <div>
                <strong>
                    {overview["rows"]}
                </strong>
                <span>rows</span>
            </div>
        </div>

        <h2>Tables</h2>

        <table>
            <tr>
                <th>Table</th>
                <th>Rows</th>
            </tr>

            {table_rows}
        </table>
        """
    )


def database_html(
    content: str,
) -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta
            name="viewport"
            content="width=device-width, initial-scale=1"
        >

        <title>Database</title>

        <style>
            body {{
                margin: 0;
                padding: 40px;
                font-family:
                    system-ui,
                    -apple-system,
                    sans-serif;
                background: #f5f5f5;
                color: #222;
            }}

            main {{
                max-width: 1400px;
                margin: 0 auto;
                background: white;
                padding: 30px;
                border-radius: 12px;
            }}

            h1 {{
                margin-top: 0;
            }}

            h2 {{
                margin-top: 35px;
            }}

            a {{
                color: #2563eb;
                text-decoration: none;
            }}

            a:hover {{
                text-decoration: underline;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
            }}

            th,
            td {{
                border: 1px solid #ddd;
                padding: 9px 10px;
                text-align: left;
                vertical-align: top;
            }}

            th {{
                background: #f0f0f0;
            }}

            td {{
                max-width: 600px;
                white-space: pre-wrap;
                word-break: break-word;
            }}

            .null {{
                color: #888;
                font-style: italic;
            }}

            .stats {{
                display: flex;
                gap: 15px;
                margin: 25px 0;
            }}

            .stats div {{
                min-width: 130px;
                padding: 18px;
                background: #f0f0f0;
                border-radius: 8px;
            }}

            .stats strong {{
                display: block;
                font-size: 28px;
            }}

            .stats span {{
                color: #666;
            }}

            .pagination {{
                display: flex;
                gap: 20px;
                margin: 20px 0;
            }}

            pre {{
                white-space: pre-wrap;
                word-break: break-word;
            }}
        </style>
    </head>

    <body>
        <main>
            {content}
        </main>
    </body>
    </html>
    """


@app.get(
    "/db",
    response_class=HTMLResponse,
)
async def database_browser():
    return render_database_page()


@app.get("/db.json")
async def database_json():
    return database.get_database_overview()


@app.get("/db/history")
async def database_history(
    entry_id: int | None = None,
    action: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    limit: int = 50,
):
    return {
        "history": database.list_history(
            entry_id=entry_id,
            action=action,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
        )
    }


@app.get(
    "/db/history/{history_id}",
)
async def database_history_row(
    history_id: int,
):
    history = database.get_history(
        history_id,
    )

    if history is None:
        raise HTTPException(
            status_code=404,
            detail="History record not found.",
        )

    return database_html(
        f"""
        <a href="/db">← Database</a>

        <h1>History {history_id}</h1>

        <pre>{
            escape(
                json.dumps(
                    history,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )
        }</pre>
        """
    )


@app.get(
    "/db/{table_name}",
    response_class=HTMLResponse,
)
async def database_table(
    table_name: str,
    page: int = 1,
):
    return render_database_page(
        table_name=table_name,
        page=page,
    )


@app.get(
    "/db/{table_name}/row/{row_id}",
    response_class=HTMLResponse,
)
async def database_row(
    table_name: str,
    row_id: int,
):
    row = database.get_table_row(
        table_name,
        row_id,
    )

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Row not found.",
        )

    return database_html(
        f"""
        <a href="/db/{escape(table_name)}">
            ← {escape(table_name)}
        </a>

        <h1>Row {row_id}</h1>

        <pre>{
            escape(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )
        }</pre>
        """
    )


@app.get("/db/{table_name}/schema")
async def database_schema(
    table_name: str,
):
    if not database.table_exists(table_name):
        raise HTTPException(
            status_code=404,
            detail="Table not found.",
        )

    return {
        "table": table_name,
        "columns": database.get_table_info(
            table_name,
        ),
    }


@app.get("/db/{table_name}/rows")
async def database_rows(
    table_name: str,
    limit: int = 50,
    offset: int = 0,
):
    if not database.table_exists(table_name):
        raise HTTPException(
            status_code=404,
            detail="Table not found.",
        )

    return {
        "table": table_name,
        "rows": database.get_table_rows(
            table_name,
            limit=limit,
            offset=offset,
        ),
        "count": database.get_table_row_count(
            table_name,
        ),
    }
