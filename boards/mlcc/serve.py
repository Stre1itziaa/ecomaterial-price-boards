"""本地预览：python serve.py 后访问 http://127.0.0.1:8792（8790/8791 被占）。"""
import functools
import http.server
import pathlib

PORT = 8792
ROOT = pathlib.Path(__file__).resolve().parent / "dashboard"


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


handler = functools.partial(NoCacheHandler, directory=str(ROOT))
with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler) as srv:
    print(f"MLCC dashboard -> http://127.0.0.1:{PORT}")
    srv.serve_forever()
