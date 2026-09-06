import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="free-api-chatgpt",
        description="Local browser-based ChatGPT interface.",
    )

    parser.add_argument(
        "--host",
        default=None,
        help="HTTP server host.",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP server port.",
    )

    parser.add_argument(
        "--profile-dir",
        default=None,
        help="Firefox persistent profile directory.",
    )

    parser.add_argument(
        "--context",
        default=None,
        help="Internal ChatGPT context.",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Firefox without a visible window.",
    )

    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Disable SQLite persistence and database action round-trips.",
    )

    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Firefox with a visible window.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.headless and args.headed:
        parser.error("--headless and --headed cannot be used together.")

    from .config import (
        HEADLESS,
        configure,
    )

    configure(
        host=args.host,
        port=args.port,
        profile_dir=args.profile_dir,
        context=args.context,
        headless=(True if args.headless else False if args.headed else HEADLESS),
        db_enabled=not args.no_db,
    )

    import uvicorn

    from .config import (
        HOST,
        PORT,
    )

    uvicorn.run(
        "free_api_chatgpt.api:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )
