"""AI 需求与退出信号板更新入口:锚点 seed → CSP 台账 → 导出看板数据。

2026-09-24 改版:连接器公告流判死(schtasks 已删,不再抓取;cninfo 表仅存档)。
用法:
  python -m tracker.update    # 锚点 seed + 导出(秒级,无网络请求)
"""

from . import tz
import argparse
import datetime as dt
import json
import pathlib

from . import audit, store
from .news_anchors import NEWS_ANCHORS
from .parts import COMPANIES, GROUP_OF, TAG_RULES

# ---- Windows GBK 控制台防御:中文输出强制 UTF-8(开源跨平台,2026-10-12) ----
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "signal.db"
CSP_LEDGER = ROOT / "data" / "csp_ledger.csv"
SNAP = ROOT / "data" / "snapshots"
DASH_DATA = ROOT / "dashboard" / "data.js"


def refresh_signals(con):
    """A 层定价行为(新浪美股)+ B 层 SEC XBRL → data/signal_state.json。"""
    from . import signals
    return signals.refresh(con)


def export_dashboard(con):
    anchors = [{"date": r["date"], "cat": r["cat"], "item": r["item"],
                "value": r["value"], "perUnit": r["per_unit"],
                "caliber": r["caliber"], "source": r["source"]}
               for r in con.execute("SELECT * FROM anchors ORDER BY date, item")]

    csp_rows = []
    if CSP_LEDGER.exists():
        import csv as _csv
        with open(CSP_LEDGER, encoding="utf-8-sig", newline="") as f:
            csp_rows = list(_csv.DictReader(f))

    dc_in = [dict(r) for r in con.execute(
        "SELECT * FROM dc_revenue ORDER BY ticker, filed_at")]
    checks = audit.run_checks(con, tz.today(), csp_rows, dc_in)
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    audit_info = {"at": tz.now().isoformat(timespec="seconds"),
                  "pass": n_fail == 0, "n": len(checks), "items": checks}

    sig_state = {}
    sig_file = ROOT / "data" / "signal_state.json"
    if sig_file.exists():
        sig_state = json.loads(sig_file.read_text(encoding="utf-8"))

    payload = {
        "generatedAt": tz.now().isoformat(timespec="seconds"),
        "sources": "CSP capex 台账(人工,csp_ledger.csv,basis 四类口径) + ABF 研报/新闻锚点(双转述纪律) + 退出日历;"
                   " A 层定价行为=新浪美股(日频自动) + B 层增长质量=SEC XBRL 机读;"
                   "cninfo 公告流 2026-09-24 判死停用,库内存档不再更新",
        "anchors": anchors,
        "cspLedger": csp_rows,
        "dcSeries": dc_in,
        "signals": sig_state,
        "audit": audit_info,
    }
    DASH_DATA.parent.mkdir(parents=True, exist_ok=True)
    with open(DASH_DATA, "w", encoding="utf-8") as f:
        f.write("window.SIGNAL_DATA = ")
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        f.write(";\n")
    print(f"[export] anchors={len(anchors)} csp={len(csp_rows)} dc={len(dc_in)} "
          f"audit={'PASS' if audit_info['pass'] else 'FAIL'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-signals", action="store_true",
                    help="跳过信号层刷新(新浪美股 + SEC XBRL 网络请求)")
    args = ap.parse_args()

    today = tz.today().isoformat()
    con = store.connect(DB)

    n_anchors = store.seed_anchors(con, NEWS_ANCHORS)
    print(f"[anchors] {n_anchors} 条在库")

    if not args.no_signals:
        try:
            refresh_signals(con)
        except Exception as e:
            print(f"[signals] FAILED {type(e).__name__}: {e} (不影响其余层)")

    from . import dc
    dc_rows = dc.crawl(SNAP)
    store.upsert_dc(con, dc_rows)

    n_ann = con.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]
    print(f"[announcements] 公告流已停用(2026-09-24 判死),存档 {n_ann} 条不再更新")

    export_dashboard(con)
    con.close()


if __name__ == "__main__":
    main()
