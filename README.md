# Free API ChatGPT

Local API for ChatGPT through browser automation.

Uses ChatGPT through Playwright and Firefox without requiring an OpenAI API key.

The application provides persistent local data and a complete chronological
application history using SQLite. Useful information such as names,
preferences, places, projects, and other relevant facts can be stored
automatically and retrieved when needed.

## Requirements

You **do not need to install Python manually**. `uv` manages the Python
environment for the project.

Use **uv 0.12 or newer**. Newer versions are supported.

```bash
uv --version
```

## Installation

Requires `uv`.

```bash
git clone https://github.com/LoXewyX/Free-API-ChatGPT.git
cd Free-API-ChatGPT
uv venv
source .venv/bin/activate
uv sync
playwright install firefox
```

## Run

```bash
uv run free-api-chatgpt
```

The API starts on:

```text
http://127.0.0.1:8000
```

## Parameters

```text
--host HOST
--port PORT
--profile-dir DIR
--context CONTEXT
--headless
--headed
```

Examples:

```bash
uv run free-api-chatgpt --port 9000
```

```bash
uv run free-api-chatgpt --profile-dir ./my-profile
```

```bash
uv run free-api-chatgpt --context "You are a concise coding assistant."
```

```bash
uv run free-api-chatgpt --headed
```

## ChatGPT Profile

The default Firefox profile is stored in:

```text
./chatgpt-profile
```

You can use a different profile with:

```bash
uv run free-api-chatgpt --profile-dir ./my-profile
```

The profile is persistent, allowing Firefox/ChatGPT state to remain between
runs.

## Persistent Data

The application uses SQLite for persistent structured data.

The database is stored at:

```text
./data/chat.db
```

The database contains two distinct types of persistent information:

* `entries` — current durable application state
* `history` — chronological application history

The assistant can automatically:

* remember useful information about the user
* create new data
* retrieve relevant data
* update existing data
* correct reliable inconsistencies
* delete data when explicitly requested

The assistant should not need to be told to remember every useful fact.

## Conversation History

Every completed `/chat` interaction is recorded in the `history` table.

History is separate from persistent memory. It records application events such
as:

* user messages
* assistant responses
* entry creation
* entry updates
* entry deletion

History records contain timestamps and can be queried to answer questions about
previous messages and application events.

For example:

```text
What did I tell you at 12:21?
```

The assistant interprets `12:21` using the user's detected local timezone,
rather than treating it as UTC.

History timestamps are stored internally in UTC. Python converts local
user-supplied time ranges to UTC before querying SQLite.

The user's timezone is detected automatically from the operating system. It is
not hardcoded into the application context.

## Database Browser

A local database browser is available at:

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

A JSON database overview is also available:

```bash
curl http://127.0.0.1:8000/db.json
```

## API

### Health

```bash
curl http://127.0.0.1:8000/health
```

Example:

```json
{
  "status": "ok",
  "context_initialized": true
}
```

### Chat

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

## Internal Context

When the application starts, it sends an internal context to ChatGPT.

The context includes:

* current database metadata
* number of tables
* total number of rows
* table names
* row counts
* table columns
* the detected user timezone
* the current local datetime
* the current UTC datetime
* rules for interacting with persistent data and history

It does **not** send all database rows.

The assistant can request relevant data through internal database actions when
needed.

Historical questions must use the internal `list_history` database action
rather than relying on the current ChatGPT conversation context.

The initialization response is not exposed through the API.

`/chat` becomes available after the initial context has been successfully
processed.

## Timezones

The application detects the user's local timezone automatically.

The timezone is represented using an IANA timezone name, for example:

```text
Europe/Madrid
```

User-supplied dates and times are interpreted in the detected local timezone.

SQLite history timestamps remain stored in UTC. Before a history query is
executed, Python converts the requested local time range to UTC using the
detected timezone.

This allows daylight-saving-time changes to be handled correctly without
hardcoding a UTC offset.

For example:

```text
User local time: 12:21
        │
        ▼
Detected timezone: Europe/Madrid
        │
        ▼
Python converts local range to UTC
        │
        ▼
SQLite history query
```

## Database Actions

ChatGPT does not access SQLite directly.

Instead, it returns structured database actions which the application validates
and executes.

Supported history actions include:

```text
list_history
get_history
update_history
delete_history
```

Supported entry actions include:

```text
list_entries
search_entries
get_entry
create_entry
update_entry
delete_entry
```

The assistant decides when persistent data needs to be created, retrieved,
updated, or deleted according to the internal context rules.

History logging is handled by the application and does not depend on the
assistant deciding whether a conversation is important enough to save.

## Endpoints

```text
GET  /health
POST /chat

GET  /db
GET  /db.json
GET  /db/{table_name}
GET  /db/{table_name}/schema
GET  /db/{table_name}/rows
GET  /db/{table_name}/row/{row_id}
```

## Architecture

```text
Client
  │
  ▼
FastAPI
  │
  ├── ChatGPT
  │     └── Playwright
  │           └── Firefox
  │
  └── SQLite
        │
        ├── entries
        │     └── Current persistent data
        │
        └── history
              └── Chronological application history
```

ChatGPT does not access SQLite directly. It requests database operations
through the application's internal action protocol.

The application executes those actions and returns the results to ChatGPT.

## License

This project is licensed under the **MIT License**.

See the [LICENSE](LICENSE) file for the full license text.
