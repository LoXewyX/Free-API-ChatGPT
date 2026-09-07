# Free API ChatGPT

Local API for ChatGPT through browser automation.

Free API ChatGPT uses a persistent Firefox browser session controlled by
Playwright to interact with ChatGPT. It exposes a local HTTP API through
FastAPI, so clients can use ChatGPT without an OpenAI API key.

The application can also maintain structured local data and a complete
chronological application history in SQLite. Persistent data and history are
handled by the application through validated database actions; ChatGPT does
not access SQLite directly.

## Features

* Browser-based ChatGPT access through Playwright + Firefox
* No OpenAI API key required
* Persistent Firefox profile
* FastAPI HTTP API
* Normal request/response chat endpoint
* Server-Sent Events streaming endpoint
* Optional SQLite persistence
* Automatic durable-data management through database actions
* Chronological application history
* Local timezone-aware history queries
* Built-in HTML database browser
* JSON database inspection endpoints
* Configurable host, port, profile directory, context, and browser mode

## Requirements

You **do not need to install Python manually**. `uv` manages the Python
environment for the project.

Requirements:

* Python 3.12+
* `uv` 0.12+
* Firefox installed by Playwright
* A ChatGPT account/session available to the persistent Firefox profile

Check your `uv` version:

```bash
uv --version
```

## Installation

Clone the repository and install the project dependencies:

```bash
git clone https://github.com/LoXewyX/Free-API-ChatGPT.git
cd Free-API-ChatGPT
uv venv
source .venv/bin/activate
uv sync
uv run playwright install firefox
```

On Windows PowerShell, activate the virtual environment with:

```powershell
.venv\Scripts\Activate.ps1
```

The application itself can also be run directly with `uv run`, so activating
the virtual environment is optional.

## First Run

Start the application in headed mode so Firefox is visible:

```bash
uv run free-api-chatgpt --headed
```

The default persistent Firefox profile is:

```text
./chatgpt-profile
```

Use that browser session to sign in to ChatGPT if necessary. The profile is
persistent, so the browser state can be reused on later runs.

After startup, the API listens on:

```text
http://127.0.0.1:8000
```

Once the initial ChatGPT context has been processed, `/health` reports
`context_initialized: true` and the chat endpoints are ready.

For normal background operation, Firefox runs headlessly by default:

```bash
uv run free-api-chatgpt
```

## Configuration

The command supports:

```text
--host HOST
--port PORT
--profile-dir DIR
--context CONTEXT
--headless
--headed
--no-db
```

### Change the port

```bash
uv run free-api-chatgpt --port 9000
```

### Use a different Firefox profile

```bash
uv run free-api-chatgpt --profile-dir ./my-profile
```

### Set a custom internal context

```bash
uv run free-api-chatgpt --context "You are a concise coding assistant."
```

### Run Firefox visibly

```bash
uv run free-api-chatgpt --headed
```

### Explicitly run headless

```bash
uv run free-api-chatgpt --headless
```

`--headless` and `--headed` cannot be used together.

### Disable SQLite persistence

```bash
uv run free-api-chatgpt --no-db
```

With `--no-db`, the application skips SQLite initialization and database
action round-trips. Chat requests return normal user-facing responses without
the `HEADER`/`BODY` database protocol.

## ChatGPT Profile

The default Firefox persistent profile is stored in:

```text
./chatgpt-profile
```

You can choose another location:

```bash
uv run free-api-chatgpt --profile-dir ./my-profile
```

The profile is reused between runs. This preserves the Firefox/ChatGPT session
state so the application does not need a fresh browser profile every time.

Keep the profile directory private because it contains persistent browser
state.

## Persistent Data

When SQLite persistence is enabled, the database is stored at:

```text
./data/chat.db
```

The database contains two different kinds of information:

* `entries` — current durable application state
* `history` — chronological application history

The assistant can manage durable information such as:

* identity and other useful personal context
* preferences and interests
* projects, plans, and intentions
* possessions and devices
* relationships
* relevant places

The application is designed to avoid duplicate entries by searching before
creating data and updating existing entries when a matching concept already
exists.

The assistant must not invent database contents. Entries are deleted only
when explicitly requested.

## Conversation History

Every completed `/chat` interaction is recorded in the `history` table when
SQLite persistence is enabled.

History is separate from persistent memory. It records application events such
as:

* user messages and final assistant responses
* entry creation
* entry updates
* entry deletion

History records include timestamps and can be queried to answer questions
about previous messages and application events.

For example:

```text
What did I tell you at 12:21?
```

The application interprets `12:21` in the detected local timezone, not as UTC.
For an exact minute, the local range is treated as:

```text
12:21:00 inclusive
12:22:00 exclusive
```

Python converts the local range to UTC before querying SQLite.

## Timezones

The application detects the operating system's local timezone automatically
and represents it as an IANA timezone name, such as:

```text
Europe/Madrid
```

History timestamps are stored internally in UTC. User-supplied dates and times
are interpreted in the detected local timezone and converted to UTC before the
SQLite query.

This avoids hardcoding a UTC offset and allows daylight-saving-time changes to
be handled correctly.

For example:

```text
User local time
      │
      ▼
Detected IANA timezone
      │
      ▼
Python converts local range to UTC
      │
      ▼
SQLite history query
```

Relative periods such as `today`, `yesterday`, and `this week` are interpreted
in the user's local timezone.

## Database Actions

ChatGPT does not execute SQL and does not access SQLite directly.

Instead, when persistence is enabled, ChatGPT returns a structured `HEADER`
containing database actions and a user-facing `BODY`. Python validates and
executes the actions, then sends the results back to ChatGPT when another
round is required.

Supported entry actions:

```text
list_entries
search_entries
get_entry
create_entry
update_entry
delete_entry
```

Supported history actions:

```text
list_history
get_history
update_history
delete_history
```

Historical questions must use `list_history`; the current ChatGPT conversation
context is not used as a substitute for application history.

History logging for completed `/chat` requests is performed by the application
and does not depend on ChatGPT deciding whether a message is worth saving.

## API

### Health

```http
GET /health
```

Example:

```bash
curl http://127.0.0.1:8000/health
```

Example response:

```json
{
  "status": "ok",
  "context_initialized": true
}
```

### Chat

```http
POST /chat
Content-Type: application/json
```

Example:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What is Python?"}'
```

Response:

```json
{
  "response": "Python is a high-level programming language..."
}
```

An empty message returns HTTP `400`. If ChatGPT context initialization has not
completed, the endpoint returns HTTP `503`.

### Streaming Chat

```http
POST /chat/stream
Content-Type: application/json
Accept: text/event-stream
```

The streaming endpoint uses Server-Sent Events (SSE).

Example:

```bash
curl -N -X POST http://127.0.0.1:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"Explain async Python."}'
```

Successful responses are emitted as SSE `data:` events containing JSON strings.
The stream ends with:

```text
data: [DONE]
```

Streaming database requests can perform multiple database-action rounds before
the final user-facing response is emitted.

### Database Browser

The local HTML database browser is available at:

```text
http://127.0.0.1:8000/db
```

It provides:

* database statistics
* table list
* row counts
* table schemas
* table rows
* individual row details
* pagination

The browser is intended for local inspection and does not provide database
mutation controls.

### Database JSON Overview

```http
GET /db.json
```

Example:

```bash
curl http://127.0.0.1:8000/db.json
```

The overview contains database metadata such as table names, row counts, and
column information. It does not dump all database rows into the initial
ChatGPT context.

### History JSON

List history records:

```http
GET /db/history
```

Optional query parameters:

```text
entry_id
action
created_after
created_before
limit
```

Example:

```bash
curl "http://127.0.0.1:8000/db/history?action=message&limit=20"
```

Retrieve one history record:

```http
GET /db/history/{history_id}
```

### Table JSON Endpoints

For an existing table:

```text
GET /db/{table_name}/schema
GET /db/{table_name}/rows
GET /db/{table_name}/row/{row_id}
```

The rows endpoint supports:

```text
limit
offset
```

Example:

```bash
curl "http://127.0.0.1:8000/db/entries/rows?limit=20&offset=0"
```

## API Endpoints

```text
GET  /health
POST /chat
POST /chat/stream

GET  /db
GET  /db.json
GET  /db/history
GET  /db/history/{history_id}
GET  /db/{table_name}
GET  /db/{table_name}/schema
GET  /db/{table_name}/rows
GET  /db/{table_name}/row/{row_id}
```

## Internal Context

When the application starts, it initializes a ChatGPT context containing the
rules needed to operate the local application.

With SQLite enabled, the context includes:

* database metadata
* number of tables
* total row count
* table names
* row counts
* table columns
* detected user timezone
* current local datetime
* current UTC datetime
* rules for persistent data and history actions

The context does **not** contain all database rows.

Relevant rows are requested through database actions only when needed.

The initialization response is not exposed through the API. Chat endpoints are
available only after initialization completes.

With `--no-db`, the application uses a simpler context and does not use
persistent-data or history actions.

## Architecture

```text
Client
  │
  ▼
FastAPI
  │
  ├── /chat
  ├── /chat/stream
  │
  ▼
ChatGPT
  │
  └── Playwright
        │
        ▼
      Firefox
        │
        └── Persistent profile

FastAPI
  │
  ▼
SQLite
  │
  ├── entries
  │     └── Current durable application state
  │
  └── history
        └── Chronological application events
```

The database-action flow is:

```text
User request
    │
    ▼
ChatGPT
    │
    ├── no database operation ──► final response
    │
    └── database actions
              │
              ▼
        Python validation
              │
              ▼
            SQLite
              │
              ▼
        action results
              │
              ▼
          ChatGPT
              │
              ▼
        final response
```

## Error Handling

The API returns standard HTTP errors for invalid requests and application
failures.

Typical responses include:

| Status | Meaning                                                    |
| ------ | ---------------------------------------------------------- |
| `400`  | Empty or invalid chat request                              |
| `404`  | Requested database table/row/history record does not exist |
| `500`  | Application, database, or action-processing error          |
| `503`  | ChatGPT context is not initialized                         |
| `504`  | Browser/ChatGPT operation timed out                        |

For `/chat/stream`, errors are sent as SSE events containing an `error` and a
`type`, followed by `[DONE]`.

## Security and Privacy Notes

This project is intended to run as a **local** service.

By default, the API binds to `127.0.0.1`, which keeps it accessible only from
the local machine. If you bind it to another interface using `--host`, the API
may become reachable by other machines on the network. Add appropriate access
controls before exposing it beyond localhost.

The persistent Firefox profile contains browser session state. Protect the
profile directory and the SQLite database like other local application data.

## License

This project is licensed under the **MIT License**.

See the [LICENSE](LICENSE) file for the full license text.
