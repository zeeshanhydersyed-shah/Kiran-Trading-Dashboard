"""Local dev server for web/ -- identical to `python -m http.server`, except
every response carries `Cache-Control: no-store`.

Why this exists: the plain stdlib server sends no cache headers at all, so
browsers fall back to heuristic caching for static JS/CSS. During active
local editing of this no-build-step site, that heuristic caching can serve a
stale module indefinitely -- confirmed directly (2026-09-13): a page load's
real <script type="module"> import kept resolving an edited file's PREVIOUS
content while a manual `fetch(url, {cache: "no-store"})` against the exact
same URL always returned the current, correct bytes. `no-store` on every
response removes that ambiguity outright, for every client, without relying
on any one browser's dev-tools cache settings.

    python web/_devserver.py [port]   # default 8765, serves this directory
"""
import http.server
import os
import sys


class NoStoreHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # always serve web/, any invocation cwd
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    http.server.test(HandlerClass=NoStoreHandler, port=port)
