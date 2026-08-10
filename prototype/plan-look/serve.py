#!/usr/bin/env python3
"""PROTOTYPE — throwaway server for plan-look UI exploration. Wipe with the branch."""

from __future__ import annotations

import http.server
import socketserver
import webbrowser
from pathlib import Path

PORT = 8765
HERE = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)


def main() -> None:
    url = f"http://127.0.0.1:{PORT}/index.html"
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print("PROTOTYPE plan-look — Ctrl+C to stop")
        print(f"Open: {url}")
        print("Variants: ?variant=timeline | agenda | checklist")
        try:
            webbrowser.open(url)
        except OSError:
            pass
        httpd.serve_forever()


if __name__ == "__main__":
    main()
