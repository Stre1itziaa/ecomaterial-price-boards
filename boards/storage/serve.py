"""本地预览：python serve.py 后访问 http://127.0.0.1:8790

dashboard 是纯静态页（data.js 内嵌数据），直接双击 index.html 也能看。
禁用缓存：每日 tracker.update 后刷新页面即可拿到最新数据。
"""
import functools
import http.server
import pathlib

PORT = 8790
ROOT = pathlib.Path(__file__).resolve().parent / "dashboard"


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


handler = functools.partial(NoCacheHandler, directory=str(ROOT))
with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler) as srv:
    print(f"dashboard -> http://127.0.0.1:{PORT}")
    srv.serve_forever()
