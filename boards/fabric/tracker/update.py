"""电子布 tracker 更新入口:公告流抓取 → 锚点 seed → 入库 → 导出看板数据。

用法:
  python -m tracker.update            # 公告流全量增量 + 锚点 + 导出(约 30 秒)
  python -m tracker.update --no-crawl # 跳过抓取,仅重导出(离线调试)
  python -m tracker.update --seed-anchors-only
"""
from . import tz
# ---- Windows GBK 控制台防御:中文输出强制 UTF-8(开源跨平台) ----
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse
import datetime as dt
import json
import pathlib

from . import audit, store, weekly
from .news_anchors import NEWS_ANCHORS
from .parts import COMPANIES, TAG_RULES

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fabric.db"
SNAP = ROOT / "data" / "snapshots"
DASH_DATA = ROOT / "dashboard" / "data.js"


def export_dashboard(con):
    anchors = [{"date": r["date"], "cat": r["cat"], "item": r["item"],
                "value": r["value"], "perUnit": r["per_unit"],
                "caliber": r["caliber"], "source": r["source"],
                "grade": r["grade"] or ""}
               for r in con.execute("SELECT * FROM anchors ORDER BY date, item")]

    anns = [{"date": r["date"], "code": r["code"], "company": r["company"],
             "title": r["title"], "tag": r["tag"], "url": r["url"]}
            for r in con.execute(
                "SELECT * FROM announcements ORDER BY date DESC, company LIMIT 400")]

    companies = []
    for code, _org, name, desc in COMPANIES:
        r = con.execute(
            "SELECT COUNT(*) n, MAX(date) latest, "
            "SUM(CASE WHEN tag != '常规' THEN 1 ELSE 0 END) n_key "
            "FROM announcements WHERE company=?", (name,)).fetchone()
        companies.append({"code": code, "name": name, "desc": desc,
                          "n": r["n"], "nKey": r["n_key"] or 0,
                          "latest": r["latest"]})

    checks = audit.run_checks(con, tz.today())
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    audit_info = {"at": tz.now().isoformat(timespec="seconds"),
                  "pass": n_fail == 0, "n": len(checks), "items": checks}

    # B2B 挂牌价层(阿里国际站,日频台阶线)
    b2b_series, b2b_latest = [], []
    for kw in con.execute("SELECT DISTINCT keyword FROM b2b_daily ORDER BY keyword"):
        name = kw["keyword"]
        pts = [{"d": r["date"], "n": r["n"], "p25": r["p25"],
                "med": r["median"], "p75": r["p75"], "unit": r["unit"]}
               for r in con.execute(
                   "SELECT * FROM b2b_daily WHERE keyword=? ORDER BY date", (name,))]
        b2b_series.append({"kw": name, "unit": pts[0]["unit"] if pts else "", "pts": pts})
    b2b_latest = [{"date": r["date"], "keyword": r["keyword"], "title": r["title"],
                   "supplier": r["supplier"], "price": r["price"], "unit": r["unit"],
                   "moq": r["moq"], "url": r["url"]}
                  for r in con.execute(
                      "SELECT * FROM b2b_listings WHERE date = "
                      "(SELECT MAX(date) FROM b2b_listings) ORDER BY keyword, price")]

    weekly_rows = [{"date": r["date"], "src": r["src"], "title": r["title"],
                    "url": r["url"], "dir": weekly.direction(r["title"])}
                   for r in con.execute(
                       "SELECT * FROM weekly_reviews ORDER BY date DESC LIMIT 12")]

    # 待核验锚点候选(搜狗微信扫描层,机器只发现不定价,人工点验)
    has_pending = con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name='pending_anchors'").fetchone()
    pending = []
    if has_pending:
        pending = [{"foundAt": r["found_at"], "pubDate": r["pub_date"],
                    "account": r["account"], "title": r["title"],
                    "excerpt": r["excerpt"], "nums": json.loads(r["nums"] or "[]"),
                    "items": json.loads(r["items"] or "[]"),
                    "status": r["status"], "url": r["url"]}
                   for r in con.execute(
                       "SELECT * FROM pending_anchors ORDER BY found_at DESC, pub_date DESC LIMIT 30")]

    payload = {
        "generatedAt": tz.now().isoformat(timespec="seconds"),
        "sources": "巨潮资讯网 cninfo 公告流(结构化,四家公司) + 新闻考古锚点(公开报道,口径分列)"
                   " + 阿里国际站 B2B 挂牌价(匿名,出口挂牌口径,2026-09-24 起)"
                   " + 玻纤周评方向层(卓创/百川,标题免费公开,周频)"
                   " + 搜狗微信候选层(公众号周评转述,待人工核验,2026-10-11 起)",
        "anchors": anchors,
        "announcements": anns,
        "companies": companies,
        "b2b": {"series": b2b_series, "latest": b2b_latest},
        "weekly": weekly_rows,
        "pending": pending,
        "audit": audit_info,
    }
    DASH_DATA.parent.mkdir(parents=True, exist_ok=True)
    with open(DASH_DATA, "w", encoding="utf-8") as f:
        f.write("window.STORAGE_DATA = ")
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        f.write(";\n")
    print(f"[export] anchors={len(anchors)} announcements={len(anns)} "
          f"audit={'PASS' if audit_info['pass'] else 'FAIL'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-crawl", action="store_true", help="跳过 cninfo 抓取")
    ap.add_argument("--no-ali", action="store_true", help="跳过阿里国际站 B2B 抓取")
    ap.add_argument("--no-weekly", action="store_true", help="跳过卓创/百川周评抓取")
    ap.add_argument("--no-wx", action="store_true", help="跳过搜狗微信候选扫描")
    ap.add_argument("--seed-anchors-only", action="store_true")
    args = ap.parse_args()

    today = tz.today().isoformat()
    con = store.connect(DB)

    n_anchors = store.seed_anchors(con, NEWS_ANCHORS)
    print(f"[anchors] {n_anchors} 条在库")
    if args.seed_anchors_only:
        export_dashboard(con)
        con.close()
        return

    if not args.no_crawl:
        from . import cninfo
        anns = cninfo.crawl(SNAP, COMPANIES, TAG_RULES, today)
        new, total = store.upsert_announcements(con, anns)
        store.log_fetch(con, "cninfo", len(anns), total, f"new={new}")
        print(f"[store] 公告新增 {new} / 在库 {total}")
    else:
        total = con.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]
        print(f"[store] 跳过抓取,公告在库 {total}")

    if not args.no_ali:
        try:
            from . import ali
            listings, dailies, warns = ali.fetch_all(today)
            by_kw = {}
            for r in listings:
                by_kw.setdefault(r["keyword"], []).append(r)
            for d in dailies:
                store.replace_b2b(con, today, d["keyword"],
                                  by_kw.get(d["keyword"], []), d)
            notes = "; ".join(warns) if warns else "ok"
            store.log_fetch(con, "alibaba-b2b", len(dailies), len(listings), notes)
            print(f"[b2b] listings={len(listings)} dailies={len(dailies)}"
                  + (f" warns={warns}" if warns else ""))
        except Exception as e:
            store.log_fetch(con, "alibaba-b2b", 0, 0, f"FAIL {type(e).__name__}: {e}")
            print(f"[b2b] FAILED {type(e).__name__}: {e} (不影响其余层)")
    else:
        print("[b2b] 跳过(--no-ali)")

    if not args.no_weekly:
        try:
            wk_rows = weekly.fetch(tz.today())
            new, total = store.upsert_weekly(con, wk_rows)
            store.log_fetch(con, "weekly-reviews", len(wk_rows), total, f"new={new}")
            print(f"[weekly] 卓创/百川周评 新增 {new} / 在库 {total}")
        except Exception as e:
            store.log_fetch(con, "weekly-reviews", 0, 0, f"FAIL {type(e).__name__}: {e}")
            print(f"[weekly] FAILED {type(e).__name__}: {e} (不影响其余层)")
    else:
        print("[weekly] 跳过(--no-weekly)")

    if not args.no_wx:
        try:
            from . import wxscan
            n = wxscan.scan_and_store(con)
            total = con.execute("SELECT COUNT(*) FROM pending_anchors "
                                "WHERE status='待核验'").fetchone()[0]
            store.log_fetch(con, "wx-scan", total, n, f"new={n}")
            print(f"[wx] 搜狗微信候选 新增 {n} / 待核验 {total}")
        except Exception as e:
            store.log_fetch(con, "wx-scan", 0, 0, f"FAIL {type(e).__name__}: {e}")
            print(f"[wx] FAILED {type(e).__name__}: {e} (不影响其余层)")
    else:
        print("[wx] 跳过(--no-wx)")

    export_dashboard(con)
    _heartbeat(con)
    con.close()
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:8890/ping/fabric_price_daily?state=ok", timeout=2)
    except Exception:
        pass


def _heartbeat(con):
    """产物级心跳:外部看门狗(butler)只需检查本文件 mtime 是否为今日。"""
    checks = audit.run_checks(con, tz.today())
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    hb = ROOT / "data" / "heartbeat.json"
    hb.write_text(json.dumps({
        "at": tz.now().isoformat(timespec="seconds"),
        "update_ok": True,
        "audit": "PASS" if n_fail == 0 else f"FAIL({n_fail})",
        "anchors": con.execute("SELECT COUNT(*) FROM anchors").fetchone()[0],
        "pending": con.execute(
            "SELECT COUNT(*) FROM pending_anchors WHERE status='待核验'").fetchone()[0],
    }, ensure_ascii=False), encoding="utf-8")
    print(f"[heartbeat] {hb.name} 已更新(audit {'PASS' if n_fail == 0 else 'FAIL'})")


if __name__ == "__main__":
    main()
