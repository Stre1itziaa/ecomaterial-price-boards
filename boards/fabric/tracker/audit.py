"""电子布 tracker 数据审计:锚点完整性/口径白名单/同口径单调 + 公告流覆盖。

电子布版特有校验(结构对齐 mlcc 版 run_checks):
1. 锚点完整性——出处与口径非空、无未来日期、主数值为正(若给);
2. 锚点口径白名单——口径必须落在 parts.CALIBERS,防止不同口径混算入库;
3. 品目覆盖——锚点覆盖 ≥4 个品目(六品类清单);
4. 同口径时序合理——同品目同口径的主数值随时间非递降(涨价周期),
   出现递降不判 FAIL,降 WARN(下跌是合法的周期信号,须展示而非拦截);
5. 公告流覆盖——四家公司在库、最新公告距抓取日 ≤15 天(在线性代理);
6. 公告打标——重要公告(调价/经营数据/定期报告/扩产)≥5 条。
"""

from . import tz
import datetime as dt
import pathlib
import sqlite3
import sys

from .parts import CALIBERS, COMPANIES, ITEMS

# ---- Windows GBK 控制台防御 ----
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fabric.db"


def run_checks(con: sqlite3.Connection, today: dt.date) -> list[dict]:
    checks = []

    def check(name, ok, note="", status=None):
        checks.append({"name": name,
                       "status": status or ("PASS" if ok else "FAIL"),
                       "note": note})

    # 1. 锚点完整性
    bad_date = con.execute("SELECT COUNT(*) FROM anchors WHERE date > ?",
                           (today.isoformat(),)).fetchone()[0]
    check("锚点无未来日期", bad_date == 0, f"异常 {bad_date} 条")
    bad = con.execute("SELECT COUNT(*) FROM anchors WHERE source='' OR caliber='' "
                      "OR value=''").fetchone()[0]
    check("锚点出处/口径/数值非空", bad == 0, f"异常 {bad} 条")
    bad_num = con.execute("SELECT COUNT(*) FROM anchors WHERE per_unit IS NOT NULL "
                          "AND per_unit <= 0").fetchone()[0]
    check("锚点主数值为正", bad_num == 0, f"异常 {bad_num} 条")

    # 2. 口径白名单
    bad_cal = [r["caliber"] for r in con.execute("SELECT DISTINCT caliber FROM anchors")
               if r["caliber"] not in CALIBERS]
    check("锚点口径全部在白名单", not bad_cal,
          "异常口径: " + "; ".join(bad_cal) if bad_cal else f"全部命中 {len(CALIBERS)} 项口径表")

    # 3. 品目覆盖
    items_hit = {r["item"] for r in con.execute("SELECT DISTINCT item FROM anchors")}
    item_families = {i.split(" ")[0] for i in items_hit}
    check("锚点品目覆盖 ≥4", len(items_hit) >= 4,
          f"覆盖 {len(items_hit)} 品目({'、'.join(sorted(item_families))});清单共 {len(ITEMS)} 品目")
    placeholders = ",".join("?" for _ in ITEMS)
    bad_items = [r["item"] for r in con.execute(
        f"SELECT DISTINCT item FROM anchors WHERE item NOT IN ({placeholders}) "
        "AND cat != '交期'", ITEMS)]
    check("价格类锚品目在清单内", not bad_items,
          "清单外价格品目: " + "; ".join(bad_items) if bad_items
          else "价格品目全部在 6 品目清单(交期类设备/材料不限)")

    # 4. 同品目同口径主数值时序(非递降为涨价的直接体现)
    rows = con.execute("SELECT item, caliber, date, per_unit FROM anchors "
                       "WHERE per_unit IS NOT NULL ORDER BY item, caliber, date").fetchall()
    seq = {}
    for r in rows:
        seq.setdefault((r["item"], r["caliber"]), []).append((r["date"], r["per_unit"]))
    n_seq = n_ok = 0
    drops = []
    for (item, cal), pts in seq.items():
        if len(pts) < 2:
            continue
        n_seq += 1
        if all(pts[i][1] <= pts[i + 1][1] * (1 + 1e-9) for i in range(len(pts) - 1)):
            n_ok += 1
        else:
            drops.append(f"{item}({cal})")
    check("同口径主数值时序非递降", n_seq == 0 or n_ok == n_seq,
          f"可时序校验 {n_seq} 组,通过 {n_ok}" + (";递降: " + "; ".join(drops) if drops else ""),
          status="PASS" if (n_seq == 0 or n_ok == n_seq) else "WARN")

    # 5. 公告流覆盖
    n_comp = con.execute("SELECT COUNT(DISTINCT company) FROM announcements").fetchone()[0]
    want = {c[2] for c in COMPANIES}
    got = {r["company"] for r in con.execute("SELECT DISTINCT company FROM announcements")}
    check("公告流四家公司在库", n_comp >= len(COMPANIES) and got == want,
          f"在库 {n_comp}/{len(COMPANIES)} 家" + ("" if got == want else f";缺 {want - got}"))
    latest = con.execute("SELECT MAX(date) d FROM announcements").fetchone()["d"]
    if latest:
        lag = (tz.today() - dt.date.fromisoformat(latest)).days
        check("公告流在线(最新披露 ≤15 天)", lag <= 15,
              f"最新公告 {latest}(距今 {lag} 天)")
    else:
        check("公告流在线(最新披露 ≤15 天)", False, "公告表为空")

    # 6. 重要公告
    n_key = con.execute("SELECT COUNT(*) FROM announcements WHERE tag != '常规'").fetchone()[0]
    check("重要公告 ≥5 条", n_key >= 5, f"打标 {n_key} 条",
          status="PASS" if n_key >= 5 else "WARN")

    # 7. B2B 挂牌价层(阿里国际站,2026-09-24 起)
    n_kw = con.execute("SELECT COUNT(DISTINCT keyword) FROM b2b_daily").fetchone()[0]
    check("B2B 层有数据(≥1 品名)", n_kw >= 1,
          f"聚合 {n_kw} 品名" if n_kw else "尚无数据(风控冷却或首日未跑)",
          status="PASS" if n_kw >= 1 else "WARN")
    bad_cur = con.execute(
        "SELECT COUNT(*) FROM b2b_listings WHERE currency != 'CNY'").fetchone()[0]
    check("B2B 挂牌币种一致(CNY)", bad_cur == 0, f"非 CNY {bad_cur} 条",
          status="PASS" if bad_cur == 0 else "WARN")
    # 每品名样本量与环比跳变
    thin, jumps = [], []
    for r in con.execute(
            "SELECT keyword, date, n, median FROM b2b_daily ORDER BY keyword, date"):
        if r["n"] < 3:
            thin.append(f"{r['keyword']}({r['date']} n={r['n']})")
    prev = {}
    for r in con.execute(
            "SELECT keyword, date, median FROM b2b_daily ORDER BY keyword, date"):
        if r["keyword"] in prev:
            last_d, last_m = prev[r["keyword"]]
            if last_m and abs(r["median"] / last_m - 1) > 0.5:
                jumps.append(f"{r['keyword']} {last_d}→{r['date']} "
                             f"{last_m}→{r['median']}")
        prev[r["keyword"]] = (r["date"], r["median"])
    check("B2B 每品名样本 ≥3", not thin,
          "样本偏薄: " + "; ".join(thin) if thin else "各品名样本量达标",
          status="PASS" if not thin else "WARN")
    check("B2B 中位数无 >50% 日跳变", not jumps,
          "跳变(需人工核对,涨价或噪声): " + "; ".join(jumps) if jumps else "环比平稳",
          status="PASS" if not jumps else "WARN")

    # 8. 周评方向层(卓创/百川,周频;标题语义无数字,在线性代理)
    has_wk = con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                         "AND name='weekly_reviews'").fetchone()
    if has_wk:
        n_wk = con.execute("SELECT COUNT(*) FROM weekly_reviews").fetchone()[0]
        if n_wk:
            wk_latest = con.execute("SELECT MAX(date) d FROM weekly_reviews").fetchone()["d"]
            lag = (today - dt.date.fromisoformat(wk_latest)).days
            check("周评层在线(最新 ≤10 天)", lag <= 10,
                  f"最新周评 {wk_latest}(距今 {lag} 天,在库 {n_wk} 条)",
                  status="PASS" if lag <= 10 else "WARN")
        else:
            check("周评层在线(最新 ≤10 天)", False,
                  "周评表为空(首次未跑或抓取失败)", status="WARN")

    # 9. 口径哨兵:B2B 出口挂牌 vs 锚点国内市场价(2026-10-11 加。
    # G75 曾因建材级 E 玻璃纱混入把中位拖低 3 倍——偏差突增=池子被污染的信号。
    # 出口挂牌与国内现货本就两个市场,常态偏差容忍 70%,超窗 WARN 提示人工核对)
    SENTINEL = [  # (品名, 锚点品目前缀, 锚点口径集, 挂牌→锚点单位换算)
        ("G75 电子纱", "G75", ("市场成交均价(元/吨)", "市场均价(元/吨)"), 1000.0),
        ("7628 电子布", "7628", ("市场成交价",), 1.0),  # 7628 幅宽≈1m,1㎡≈1米
    ]
    drift = []
    for kw_name, item_prefix, cals, factor in SENTINEL:
        last = con.execute(
            "SELECT median, unit, date FROM b2b_daily WHERE keyword=? "
            "ORDER BY date DESC LIMIT 1", (kw_name,)).fetchone()
        ph = ",".join("?" for _ in cals)
        ref = con.execute(
            f"SELECT per_unit, date FROM anchors WHERE item LIKE ? "
            f"AND caliber IN ({ph}) AND per_unit IS NOT NULL "
            "ORDER BY date DESC LIMIT 1", (item_prefix + "%", *cals)).fetchone()
        if last and ref and last["median"]:
            dev = abs(last["median"] * factor / ref["per_unit"] - 1)
            if dev > 0.70:
                drift.append(f"{kw_name} {last['date']} 挂牌{last['median']}"
                             f"{last['unit']} vs 锚点{ref['per_unit']:.0f}"
                             f"({ref['date']}),偏差 {dev:.0%}")
    check("B2B挂牌与锚点国内价偏差(口径哨兵)", not drift,
          "超窗(疑污染或口径异动,人工核对): " + "; ".join(drift) if drift
          else "G75/7628 挂牌-锚点偏差 ≤70% 正常带",
          status="PASS" if not drift else "WARN")

    return checks


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    checks = run_checks(con, tz.today())
    con.close()
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    n_warn = sum(1 for c in checks if c["status"] == "WARN")
    lines = [f"# 电子布数据审计报告 {tz.now():%Y-%m-%d %H:%M}", "",
             f"结论:{'❌ 存在 FAIL' if n_fail else '✅ 通过'}"
             + (f"(含 {n_warn} 项 WARN)" if n_warn else ""), ""]
    for c in checks:
        lines.append(f"- [{c['status']}] {c['name']}" + (f" —— {c['note']}" if c["note"] else ""))
    report = "\n".join(lines)
    print(report)
    (ROOT / "data" / "audit_report.md").write_text(report, encoding="utf-8")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
