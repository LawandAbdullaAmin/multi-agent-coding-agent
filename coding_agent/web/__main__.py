"""Startet die Weboberfläche: python -m coding_agent.web

Der Server ist nur auf diesem Rechner erreichbar (127.0.0.1), weil die Oberfläche
API-Guthaben verbraucht und Dateien ändert.
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
    parser = argparse.ArgumentParser(description="Weboberfläche des Coding-Agenten")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="Browser nicht automatisch öffnen")
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    print(f"Coding-Agent läuft auf {url}  (beenden mit Strg+C)")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run("coding_agent.web.server:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
