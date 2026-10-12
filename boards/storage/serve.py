"""本地预览：python serve.py 后访问 http://127.0.0.1:8790

dashboard 是纯静态页（data.js 内嵌数据），直接双击 index.html 也能看。
禁用缓存：每日 tracker.update 后刷新页面即可拿到最新数据。
"""
import functools
import os
import http.server
import pathlib

# ---- Windows GBK 控制台防御:中文输出强制 UTF-8(开源跨平台,2026-10-12) ----
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


PORT = int(os.environ.get("PORT", "8790"))
ROOT = pathlib.Path(__file__).resolve().parent / "dashboard"


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


handler = functools.partial(NoCacheHandler, directory=str(ROOT))
with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler) as srv:
    print(f"dashboard -> http://127.0.0.1:{PORT}")
    srv.serve_forever()
