"""Starts the web interface: python -m coding_agent.web

The server is only reachable from this machine (127.0.0.1), because the interface
uses API credit and changes files.
"""

import argparse
import sys
import threading
import webbrowser

import uvicorn
from dotenv import load_dotenv

from coding_agent.runs import PROJECT_DIR


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(PROJECT_DIR / ".env")
    parser = argparse.ArgumentParser(description="Web interface of the coding agent")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    print(f"Coding agent running at {url}  (stop with Ctrl+C)")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run("coding_agent.web.server:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
