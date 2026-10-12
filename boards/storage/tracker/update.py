"""更新入口：抓取 -> 解析 -> 入库 -> 导出 dashboard 数据。

用法：
  python -m tracker.update             # 抓当天
  python -m tracker.update --reparse   # 对 data/snapshots/ 里的快照重解析入库（不联网）
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
import re

from . import fetch, parse, store

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "storage.db"
SNAP = ROOT / "data" / "snapshots"
DASH_DATA = ROOT / "dashboard" / "data.js"

# 看板核心白名单：(source, family, name 子串)。采集端保持全量，仅导出层过滤。
CORE_SPECS = [
    ("CFM", "CFM 指数", "DRAM指数"),
    ("CFM", "CFM 指数", "NAND指数"),
    ("TrendForce", "DRAM", "DDR5 16Gb (2Gx8) 4800/5600"),
    ("TrendForce", "DRAM", "DDR4 16Gb (2Gx8) 3200"),
    ("TrendForce", "DRAM", "DDR4 8Gb (1Gx8) 3200"),
    ("TrendForce", "Wafer", "512Gb TLC"),
    ("CFM", "NAND Wafer", "512Gb TLC"),
    ("CFM", "NAND Wafer", "1Tb QLC"),
    ("TrendForce", "Module", "DDR5 UDIMM 16GB 4800/5600"),
    ("TrendForce", "Module", "DDR5 RDIMM 32GB 4800/5600"),
    ("CFM", "内存条(渠道)", "DDR5 UDIMM 16GB 5600"),
    ("CFM", "内存条(渠道)", "DDR4 UDIMM 16GB 3200"),
    ("CFM", "SSD(渠道)", "Channel SSD 1TB PCIe 4.0"),
    ("CFM", "SSD(行业)", "OEM SSD 1TB PCIe 4.0"),
    ("TrendForce", "SSD", "Samsung 990 Pro 1 TB"),
    # ---- 2026-10-12 扩容:TF 免费页 09-29 收缩停更板块,由 CFM 渠道价接棒 ----
    ("CFM", "内存条(渠道)", "DDR4 UDIMM 8GB 3200"),
    ("CFM", "内存条(渠道)", "DDR4 UDIMM 32GB 3200"),
    ("CFM", "内存条(渠道)", "DDR5 UDIMM 8GB 5600"),
    ("CFM", "内存条(渠道)", "DDR5 UDIMM 16GB 6000"),
    ("CFM", "内存条(渠道)", "DDR5 UDIMM 32GB 5600"),
    ("CFM", "SSD(渠道)", "Channel SSD 1TB PCIe 3.0"),
    ("CFM", "SSD(渠道)", "Channel SSD 512GB PCIe 4.0"),
    ("CFM", "SSD(行业)", "OEM SSD 1TB PCIe 3.0"),
    ("CFM", "eMMC", "eMMC 8GB 5.1"),
    ("CFM", "eMMC", "eMMC 64GB 5.1"),
    ("CFM", "UFS", "UFS 2.2 64GB"),
    ("CFM", "UFS", "UFS 2.2 256GB"),
    ("CFM", "LPDDR", "LPDDR4X"),
]


def _is_core(row) -> bool:
    if row["family"] in ("HDD 企业盘", "HDD NAS盘"):
        return True
    return any(row["source"] == s and row["family"] == f and spec in row["name"]
               for s, f, spec in CORE_SPECS)


# 第二梯队："更多品种"默认折叠组（数据全量入库，仅看板折叠展示）
TIER2_SPECS = [
    ("CFM", "eMMC", "eMMC 8GB 5.1"),
    ("CFM", "UFS", "UFS 2.2 64GB"),
    ("CFM", "LPDDR", "LPDDR4X 64Gb"),
    ("CFM", "闪存卡", "渠道市场MicroSD 16GB"),
    ("CFM", "NAND Wafer", "256Gb TLC"),
    ("CFM", "DRAM 颗粒", "DDR5 24Gb Major"),
    ("TrendForce", "GDDR", "GDDR6"),
    ("CFM", "SSD(渠道)", "Channel SSD 1TB"),
]

FREQ_DAYS = {"daily": 1, "weekly": 7}  # 月/季更仅展示身份徽章，不做 staleness 巡检


def _tier(row) -> int:
    if _is_core(row):
        return 1
    return 2 if any(row["source"] == s and row["family"] == f and spec in row["name"]
                    for s, f, spec in TIER2_SPECS) else 0


def load_or_fetch(reparse: bool) -> dict[str, str]:
    if reparse:
        pages = {}
        for p in sorted(SNAP.glob("*.html")):
            m = re.match(r"^\d{8}_(dram|flash)$", p.stem)
            if m:
                pages[m.group(1)] = p.read_text(encoding="utf-8")
        print(f"[reparse] 从 {len(pages)} 份 TrendForce 快照重解析")
        return pages
    return fetch.fetch_all(SNAP)


def export_dashboard(con):
    import datetime as dt2
    from .audit import run_checks

    today = tz.today()
    all_products = [dict(row) for row in con.execute(
        "SELECT id, source, family, section, name, unit, vendors, freq FROM products "
        "WHERE active=1 ORDER BY id")]
    products = []
    for p in all_products:
        t = _tier(p)
        if t:
            p["tier"] = t
            products.append(p)
    keep = {p["id"] for p in products}
    quotes = []
    for row in con.execute(
            "SELECT product_id, date, avg, change_pct, high, low FROM quotes "
            "ORDER BY date, product_id"):
        if row["product_id"] in keep:
            quotes.append([row["product_id"], row["date"], row["avg"],
                           row["change_pct"], row["high"], row["low"]])

    # 审计结论上屏
    checks = run_checks(con, today)
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    audit = {"at": tz.now().isoformat(timespec="seconds"),
             "pass": n_fail == 0, "n": len(checks),
             "items": [{"name": c["name"], "status": c["status"], "note": c["note"]}
                       for c in checks]}

    # 采集健康巡检（X2）：daily/weekly 产品超 1.5× 周期未更新 WARN，超 3× ERROR。
    # TF_STALE_EXEMPT:TrendForce 中文免费页 2026-09-29 结构性收缩停更的板块,
    # 已由 CFM 渠道价/DXEN 接棒——不再计 stale(否则常驻 WARN 掩盖真信号)。
    TF_STALE_EXEMPT = {
        "DDR5 UDIMM 16GB 4800/5600", "DDR4 UDIMM 16GB 3200", "DDR5 24Gb Major",
        "Samsung 990 Pro 1 TB (PCIe 4.0 X4)", "Channel SSD 1TB PCIe 3.0",
        "Channel SSD 1TB PCIe 4.0", "OEM SSD 1TB PCIe 4.0", "eMMC 8GB 5.1",
        "LPDDR4X 64Gb", "UFS 2.2 64GB",
    }
    # 2026-10-12 修订:age 按【工作日】计——现货评估价周末不更新(2026-10-11 实测
    # 9 条 daily 序列被周末误伤 WARN),周一查周五报价 age=3 自然日但仅 1 个工作日。
    def _workday_age(last_iso, ref):
        d0 = dt.date.fromisoformat(last_iso)
        n, cur = 0, d0
        while cur < ref:
            cur += dt.timedelta(days=1)
            if cur >= ref:   # 当日 18:40 更新未到时点,不计「错过」
                break
            if cur.weekday() < 5:
                n += 1
        return n
    stale, status = [], "ok"
    period_by_id = {p["id"]: FREQ_DAYS.get(p["freq"]) for p in products}
    last_by_id = {row["product_id"]: row["ld"] for row in con.execute(
        "SELECT product_id, MAX(date) ld FROM quotes WHERE product_id IN (%s) GROUP BY product_id"
        % ",".join(str(i) for i in keep))}
    name_by_id = {p["id"]: p["name"] for p in products}
    source_by_id = {p["id"]: p["source"] for p in products}
    for pid, period in period_by_id.items():
        if not period or pid not in last_by_id:
            continue
        if source_by_id.get(pid) == "TrendForce" and name_by_id[pid] in TF_STALE_EXEMPT:
            continue
        age = _workday_age(last_by_id[pid], today)
        if age > 3 * period:
            stale.append({"name": name_by_id[pid], "age": age, "level": "error"})
            status = "error"
        elif age > 1.5 * period:
            stale.append({"name": name_by_id[pid], "age": age, "level": "warn"})
            status = status == "error" and "error" or "warn"
    health = {"status": status, "stale": stale}

    payload = {
        "generatedAt": tz.now().isoformat(timespec="seconds"),
        "sources": "TrendForce 集邦咨询 trendforce.cn/price + DRAMeXchange 英文站首页（停更板块救援）+ CFM闪存市场 chinaflashmarket.com（公开页）",
        "products": products,
        "quotes": quotes,
        "audit": audit,
        "health": health,
    }
    DASH_DATA.parent.mkdir(parents=True, exist_ok=True)
    with open(DASH_DATA, "w", encoding="utf-8") as f:
        f.write("window.STORAGE_DATA = ")
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        f.write(";\n")
    print(f"[export] {DASH_DATA}  products={len(products)}/{len(all_products)} "
          f"quotes={len(quotes)} audit={'PASS' if audit['pass'] else 'FAIL'} health={status}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reparse", action="store_true", help="重解析本地快照，不联网")
    ap.add_argument("--with-cfm", action="store_true", help="立即全量抓取 CFM 闪存市场（约3分钟）")
    ap.add_argument("--no-cfm", action="store_true", help="跳过 CFM 抓取(默认每周一自动)")
    ap.add_argument("--no-hdd", action="store_true", help="跳过 HDD 零售抓取（ServerPartDeals）")
    ap.add_argument("--no-dxen", action="store_true",
                    help="跳过 DRAMeXchange 英文首页救援腿（TF 中文免费页停更板块）")
    args = ap.parse_args()

    # 连接提前建立：dxen 救援腿需要对回库内产品身份（不新建产品）
    con = store.connect(DB)
    pages = load_or_fetch(args.reparse)
    rows = parse.parse_snapshots(pages)
    # TF 各板块真实更新节奏（免费页实测：模组/GDDR/晶圆现货周更，颗粒现货日更，
    # SSD 合约季更）——freq 元数据必须与事实一致，否则巡检与徽章传播错误
    TF_FREQ = {
        ("DRAM", "现货价"): "daily", ("NAND", "现货价"): "weekly",
        ("Wafer", "现货价"): "weekly", ("Memory Card", "现货价"): "weekly",
        ("Module", "现货价"): "weekly", ("GDDR", "现货价"): "weekly",
        ("DRAM", "合约价"): "monthly", ("NAND", "合约价"): "monthly",
        ("SSD", "合约价"): "quarterly",
    }
    for r in rows:
        if r.source == "TrendForce":
            r.freq = TF_FREQ.get((r.family, r.section), r.freq)
        # CFM 现货(日) 家族（晶圆/存储卡/U盘）的密集历史来自首次详情图回填，
        # 此后仅 cfm-weekly 每周续行——freq 按交付节奏=weekly，否则周间必然误报 staleness
        if r.source == "CFM" and r.family in ("NAND Wafer", "闪存卡",
                                              "U盘 USB2.0", "U盘 USB3.0"):
            r.freq = "weekly"
    print(f"[parse] TrendForce {len(rows)} 条")

    if not args.no_dxen and not args.reparse:
        from . import dxen
        dx_rows = dxen.crawl(SNAP, con, tz.today().isoformat())
        rows = rows + dx_rows

    # CFM 渠道价为周报节奏:每周一随任务全量抓(上周报价),工作日手动 --with-cfm
    cfm_scheduled = tz.today().weekday() == 0 and not args.no_cfm
    if (args.with_cfm or cfm_scheduled) and not args.reparse:
        from . import cfm
        cfm_rows = cfm.crawl(ROOT / "data" / "snapshots")
        print(f"[parse] CFM {len(cfm_rows)} 条（含历史序列）")
        rows = rows + cfm_rows

    if not args.no_hdd and not args.reparse:
        from . import hdd
        hdd_rows = hdd.crawl(SNAP)
        print(f"[hdd] ServerPartDeals {len(hdd_rows)} 条")
        rows = rows + hdd_rows

    if not rows:
        print("[abort] 未解析到任何行情，请检查页面结构是否变更")
        return

    products, quotes = store.upsert_rows(con, rows)

    # HDD 涨跌幅回填：对库内上一有价日（SPD 页面无涨跌幅字段，口径=本库序列自身）
    for (pid,) in con.execute(
            "SELECT id FROM products WHERE source='SPD'").fetchall():
        last2 = con.execute(
            "SELECT date, avg FROM quotes WHERE product_id=? ORDER BY date DESC LIMIT 2",
            (pid,)).fetchall()
        if len(last2) == 2 and last2[0]["date"] == tz.today().isoformat():
            chg = round(100.0 * (last2[0]["avg"] / last2[1]["avg"] - 1), 2)
            con.execute("UPDATE quotes SET change_pct=? WHERE date=? AND product_id=?",
                        (chg, last2[0]["date"], pid))
    con.commit()

    store.log_fetch(con, ",".join(pages), products, quotes,
                    "ok" if not args.reparse else "reparse")
    print(f"[store] UPSERT 完成：{products} 产品 / {quotes} 行")
    export_dashboard(con)
    con.close()


if __name__ == "__main__":
    main()
