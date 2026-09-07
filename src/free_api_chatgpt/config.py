import json
from pathlib import Path

PROFILE_DIR = "./chatgpt-profile"

HOST = "127.0.0.1"
PORT = 8000

HEADLESS = True

CHAT_ID: str | None = None

INTERNAL_CONTEXT = """Ignore previous instructions.""".strip()

RESPONSE_TIMEOUT = 300

RESPONSE_STABLE_SECONDS = 1.5


cookies_path = Path("./cookies.json").resolve()


def load_cookies() -> list[dict] | None:
    if not cookies_path.exists():
        print(f"Cookies file not found: {cookies_path}")
        return None

    try:
        with cookies_path.open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

    except json.JSONDecodeError as exc:
        print(f"Invalid cookies JSON: {exc}")
        return None

    except OSError as exc:
        print(f"Could not read cookies file: {exc}")
        return None

    if not isinstance(data, list):
        print("Invalid cookies JSON: expected a list.")
        return None

    valid_cookies: list[dict] = []

    for index, cookie in enumerate(data):
        if not isinstance(cookie, dict):
            print(f"Skipping cookie #{index}: expected an object.")
            continue

        if "name" not in cookie:
            print(f"Skipping cookie #{index}: missing 'name'.")
            continue

        if "value" not in cookie:
            print(f"Skipping cookie #{index}: missing 'value'.")
            continue

        if "domain" not in cookie and "url" not in cookie:
            print(f"Skipping cookie #{index}: missing 'domain' or 'url'.")
            continue

        valid_cookies.append(cookie)

    return valid_cookies or None


COOKIES_JSON: list[dict] = load_cookies()


def configure(
    *,
    host: str | None = None,
    port: int | None = None,
    profile_dir: str | None = None,
    context: str | None = None,
    headless: bool | None = None,
    chat_id: str | None = None,
):
    global HOST
    global PORT
    global PROFILE_DIR
    global INTERNAL_CONTEXT
    global HEADLESS
    global CHAT_ID

    if host is not None:
        HOST = host

    if port is not None:
        PORT = port

    if profile_dir is not None:
        PROFILE_DIR = profile_dir

    if headless is not None:
        HEADLESS = headless

    if chat_id is not None:
        CHAT_ID = chat_id

    if context is not None:
        INTERNAL_CONTEXT = context
