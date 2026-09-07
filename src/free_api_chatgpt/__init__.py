import argparse

import uvicorn

from free_api_chatgpt.config import HOST, PORT, configure


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
        "--chat-id",
        default=None,
        help="ChatGPT conversation ID to open.",
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

    configure(
        host=args.host,
        port=args.port,
        profile_dir=args.profile_dir,
        context=args.context,
        headless=not args.headed,
        chat_id=args.chat_id,
    )

    uvicorn.run(
        "free_api_chatgpt.api:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )
