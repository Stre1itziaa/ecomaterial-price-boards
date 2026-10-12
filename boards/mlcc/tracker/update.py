"""MLCC 更新入口：双源抓取 → 入库 → 导出看板数据 → 审计结论嵌入。

用法：
  python -m tracker.update            # 双源全量（云汉 curl + 立创 Playwright，约 5 分钟）
  python -m tracker.update --ickey-only
  python -m tracker.update --lcsc-only
"""

from . import tz
import argparse
import datetime as dt
import json
import pathlib

from . import audit, store
from .news_anchors import NEWS_ANCHORS
from .parts import PARTS

# ---- Windows GBK 控制台防御:中文输出强制 UTF-8(开源跨平台,2026-10-12) ----
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "mlcc.db"
SNAP = ROOT / "data" / "snapshots"
DASH_DATA = ROOT / "dashboard" / "data.js"

# Mouser 参照腿：只覆盖国内双源同时缺货、且 Mouser 中国站确有报价的料号
# （单件挂牌价口径，与起订档不可比，不入双源价差审计）。
# 注：GRM188R61E105MA12D 已核实 mouser.cn 无报价（详情页仅相似品推荐，
# 疑行业性停产/转型号），不硬凑——其 LCSC 冻结价+缺货标记即真实状态。
MOUSER_PNS = {
    "CGA3E2X7R1H104K080AA",   # TDK 车规，LCSC 缺货（2026-10 起），Mouser 有挂牌价
}
# ICKey 限流退化（2026-10 实测：17 料号日频只回 3 条，且 3 条无独家覆盖），
# 降为周一交叉校验；LCSC 为日频主力。
ICKEY_WEEKDAY = 0  # 周一


def _conclusion(con, products, today):
    """结论横幅(灯只管数据健康度:新鲜度/覆盖/管线;价格异动是现象展示,不进灯)。
    判定规则表驱动,verdict 规则:单层黄=观察;同层两项或跨层=橙;全绿=无异常。"""
    lights, drivers, normals = {}, [], []
    # 新鲜度:立创最新 ≤2 天绿,>2 黄;云汉(周一节奏)距上个周一 ≤7 天绿
    d_lcsc = con.execute("SELECT MAX(q.date) d FROM quotes q JOIN products p ON p.id=q.product_id WHERE p.source='LCSC'").fetchone()["d"]
    d_ickey = con.execute("SELECT MAX(q.date) d FROM quotes q JOIN products p ON p.id=q.product_id WHERE p.source='ICKey'").fetchone()["d"]
    lag_lcsc = (today - dt.date.fromisoformat(d_lcsc)).days if d_lcsc else 999
    lights["fresh"] = "ok" if lag_lcsc <= 2 else "wa"
    if lag_lcsc > 2: drivers.append(f"立创最新数据 {d_lcsc}(距今 {lag_lcsc} 天)")
    else:
        n_lcsc = con.execute(
            "SELECT COUNT(DISTINCT p.part) FROM quotes q JOIN products p "
            "ON p.id=q.product_id WHERE q.date=? AND p.source='LCSC'", (d_lcsc,)).fetchone()[0]
        normals.append(f"立创 {n_lcsc} 序列全在线(最新 {d_lcsc})")
    # 覆盖:基线日(=云汉最新日,周一交叉点)覆盖料号 ≥14 绿
    n_base = con.execute(
        "SELECT COUNT(DISTINCT p.part) FROM products p JOIN quotes q ON q.product_id=p.id "
        "WHERE q.date=(SELECT MAX(q.date) FROM quotes q JOIN products p "
        "ON p.id=q.product_id WHERE p.source='ICKey')").fetchone()[0]
    lights["cover"] = "ok" if n_base >= 14 else "wa"
    if n_base < 14: drivers.append(f"基线日覆盖 {n_base} 料号(<14)")
    # 管线:锚点最新距 today ≤60 天绿;pending 待核验=0 绿
    # (MLCC 锚点不入库,从 news_anchors 常量读;跳过"2026-09-中"这类非 ISO 日期)
    iso_dates = []
    for a in NEWS_ANCHORS:
        try:
            iso_dates.append(dt.date.fromisoformat(a[0]).isoformat())
        except ValueError:
            pass
    last_anchor = max(iso_dates) if iso_dates else None
    lag_anchor = (today - dt.date.fromisoformat(last_anchor)).days if last_anchor else 999
    n_pending = con.execute("SELECT COUNT(*) FROM pending_anchors WHERE status='待核验'").fetchone()[0]         if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pending_anchors'").fetchone() else 0
    pipe_ok = lag_anchor <= 60 and n_pending == 0
    lights["pipe"] = "ok" if pipe_ok else "wa"
    if lag_anchor > 60: drivers.append(f"锚点距 {last_anchor} 已 {lag_anchor} 天(窗口 60 天)")
    if n_pending: drivers.append(f"{n_pending} 条候选待人工核验")
    normals.append(f"距最近原厂调价锚点 {lag_anchor} 天(窗口 60 天)")
    # verdict:全绿 / 有黄
    n_wa = sum(1 for v in lights.values() if v != "ok")
    if n_wa == 0:
        verdict = "✓ 三层均无异常"; level = "ok"
    else:
        wa_names = {"fresh": "新鲜度", "cover": "覆盖", "pipe": "管线"}
        bad = [wa_names[k] for k, v in lights.items() if v != "ok"]
        verdict = f"{'/'.join(bad)} 层观察中 · 无红色行动信号" if n_wa < 3 else "多层观察中 · 建议人工巡检"
        level = "wa"
    return {"verdict": verdict, "level": level,
            "lights": {"fresh": lights["fresh"], "cover": lights["cover"], "pipe": lights["pipe"]},
            "drivers": drivers, "normals": normals,
            "lastReview": tz.now().isoformat(timespec="seconds"),
            "nextScan": "每日 20:10"}


def _wx_flag_state():
    """候选层扫描状态:正常 None;熔断中返回冷却截止日(供看板明示)。"""
    try:
        from .wxscan import FLAG as WX_FLAG
        if WX_FLAG.exists():
            last = json.loads(WX_FLAG.read_text())["last_captcha"]
            end = dt.date.fromisoformat(last) + dt.timedelta(days=2)
            return {"cooldown": True, "until": end.isoformat(), "last": last}
    except Exception:
        pass
    return None


def export_dashboard(con):
    products = [dict(r) for r in con.execute(
        "SELECT id, source, part, brand, seg, descr, unit, freq FROM products "
        "WHERE active=1 ORDER BY id")]
    keep = {p["id"] for p in products}
    quotes = []
    for r in con.execute(
            "SELECT product_id, date, price, stock, moq, ladder FROM quotes ORDER BY date, product_id"):
        if r["product_id"] not in keep:
            continue
        ladder = json.loads(r["ladder"]) if r["ladder"] else None
        # 存储版前端兼容：[pid, date, avg, chg, high, low] + MLCC 扩展
        high = ladder[0][1] if ladder else r["price"]      # 首档=最高价
        low = ladder[-1][1] if ladder else r["price"]      # 末档=最低价
        quotes.append([r["product_id"], r["date"], r["price"], None, high, low,
                       r["stock"], r["moq"]])

    checks = audit.run_checks(con, tz.today())
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    audit_info = {"at": tz.now().isoformat(timespec="seconds"),
                  "pass": n_fail == 0, "n": len(checks),
                  "items": checks}

    payload = {
        "generatedAt": tz.now().isoformat(timespec="seconds"),
        "sources": "立创商城 szlcsc.com（日频主力，起订档单价 CNY）+ 云汉芯城 ickey.cn（周一交叉校验）+ Mouser 中国站（缺货料号单件价参照）",
        "products": products,
        "quotes": quotes,
        "audit": audit_info,
        "conclusion": _conclusion(con, products, tz.today()),
        "pendingState": _wx_flag_state(),
        "pending": [
            {"foundAt": r["found_at"], "pubDate": r["pub_date"],
             "account": r["account"], "title": r["title"],
             "excerpt": r["excerpt"], "nums": json.loads(r["nums"] or "[]"),
             "items": json.loads(r["items"] or "[]"),
             "status": r["status"], "url": r["url"]}
            for r in con.execute(
                "SELECT * FROM pending_anchors ORDER BY found_at DESC, pub_date DESC LIMIT 30")
        ],
        "newsAnchors": [
            {"date": d, "cat": c, "item": i, "value": v,
             "perUnit": p, "caliber": cal, "source": src, "grade": g}
            for d, c, i, v, p, cal, src, g in NEWS_ANCHORS
        ],
    }
    DASH_DATA.parent.mkdir(parents=True, exist_ok=True)
    with open(DASH_DATA, "w", encoding="utf-8") as f:
        f.write("window.MLCC_DATA = ")
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        f.write(";\n")
    print(f"[export] products={len(products)} quotes={len(quotes)} "
          f"audit={'PASS' if audit_info['pass'] else 'FAIL'}")


def _heartbeat(con):
    """产物级心跳:外部看门狗(butler)只需检查本文件 mtime 是否为今日。"""
    checks = audit.run_checks(con, tz.today())
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    hb = ROOT / "data" / "heartbeat.json"
    hb.write_text(json.dumps({
        "at": tz.now().isoformat(timespec="seconds"),
        "update_ok": True,
        "audit": "PASS" if n_fail == 0 else f"FAIL({n_fail})",
        "products": con.execute(
            "SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0],
        "quotes": con.execute("SELECT COUNT(*) FROM quotes").fetchone()[0],
    }, ensure_ascii=False), encoding="utf-8")
    print(f"[heartbeat] {hb.name} 已更新(audit {'PASS' if n_fail == 0 else 'FAIL'})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ickey-only", action="store_true")
    ap.add_argument("--lcsc-only", action="store_true")
    ap.add_argument("--mouser-only", action="store_true")
    ap.add_argument("--no-wx", action="store_true", help="跳过搜狗微信候选扫描")
    ap.add_argument("--export-only", action="store_true",
                    help="跳过抓取,仅重导出看板数据(用库内现量)")
    args = ap.parse_args()

    today = tz.today().isoformat()
    quotes = []
    sources = []
    run_ickey = args.ickey_only or (
        not args.export_only and not args.lcsc_only and not args.mouser_only
        and tz.today().weekday() == ICKEY_WEEKDAY)
    run_lcsc = (not args.ickey_only and not args.mouser_only
                and not args.export_only)
    run_mouser = (not args.ickey_only and not args.lcsc_only
                  and not args.export_only)

    if run_ickey:
        from . import ickey
        qs = ickey.crawl(SNAP, PARTS, today)
        print(f"[ickey] {len(qs)} 条")
        quotes += qs
        sources.append("ICKey")
    elif not args.lcsc_only and not args.mouser_only:
        print(f"[ickey] 今日非周一，周频交叉校验跳过（--ickey-only 可手动跑）")
    if run_lcsc:
        from . import lcsc
        qs = lcsc.crawl(SNAP, PARTS, today)
        print(f"[lcsc] {len(qs)} 条")
        quotes += qs
        sources.append("LCSC")
    if run_mouser:
        from . import mouser
        mouser_parts = [p for p in PARTS if p[0] in MOUSER_PNS]
        qs = mouser.crawl(SNAP, mouser_parts, today)
        print(f"[mouser] {len(qs)} 条")
        quotes += qs
        sources.append("Mouser")

    con = store.connect(DB)
    if args.export_only:
        export_dashboard(con)
        _heartbeat(con)
        con.close()
        print("[export-only] 完成(未抓取)")
        return
    parts_n, rows_n = store.upsert(con, quotes)
    store.log_fetch(con, ",".join(sources), parts_n, rows_n, "ok")
    print(f"[store] {parts_n} 产品 / {rows_n} 行")
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
    export_dashboard(con)
    _heartbeat(con)
    con.close()
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:8890/ping/mlcc_price_daily?state=ok", timeout=2)
    except Exception:
        pass


if __name__ == "__main__":
    main()
