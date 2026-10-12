"""看板总入口 + 轻量汇总 API：python serve.py 后访问 http://127.0.0.1:8800。
/api/summary 只读各项目 SQLite（mode=ro，不打扰写端），60 秒进程内缓存。
要点计算逻辑在 summary.py（与 Vercel 静态发布共用）。"""
import functools
import os
import http.server
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from summary import build_summary as summary

# ---- Windows GBK 控制台防御:中文输出强制 UTF-8(开源跨平台,2026-10-12) ----
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


PORT = int(os.environ.get("PORT", "8800"))
ROOT = pathlib.Path(__file__).resolve().parent


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/api/summary":
            body = json.dumps(summary(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *a):  # 静默访问日志
        pass


with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), NoCacheHandler) as srv:
    print(f"Dashboard hub -> http://127.0.0.1:{PORT}")
    srv.serve_forever()
