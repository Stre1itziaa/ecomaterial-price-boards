"""阿里国际站 B2B 挂牌价层(日频台阶线,免账号)。

为什么是阿里国际站:1688 搜索必须登录且强制补个人信息(2026-09-24 用户红线放弃,
云汉/立创对电子布无 SKU);alibaba.com 匿名可搜,中国供应商出口挂牌价(¥/㎡)。
信噪比中等→标题严格过滤:必含规格 token(如 7628)+品类词(电子/PCB/CCL),
排除涂层/铝箔/高硅/清洁布等混入;聚合同单位挂牌取 P25/中位/P75——中位线为
日频台阶信号,与锚点层口径分列绝不混算。

风控纪律(2026-09-24 实测):短时高频会把 IP 打进验证码小黑屋(有头/无头/真内核
一律拦)。因此:①每日只在 update 里跑一轮(5 页);②命中验证码即写熔断标记,
冷却 COOLDOWN_DAYS 天不去碰;③多日被拦时可用 `python -m tracker.ali unlock`
人工拖一次滑块(无账号无个人信息)写 anti-bot cookie,headless 端复用同 UA。

口径:出口挂牌价(非成交价),台阶式移动(挂牌随涨价潮调价),自 2026-09-24 累积。
"""
from . import tz
import datetime as dt
import json
import pathlib
import re
import statistics
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fabric.db"
SNAP = ROOT / "data" / "snapshots" / "ali"
FLAG = ROOT / "data" / "ali_flag.json"      # 熔断标记 {"last_captcha": date}
STATE = ROOT / "data" / "ali_state.json"    # unlock 存的 anti-bot cookie
COOLDOWN_DAYS = 1

# 有头/无头统一用同一个真 Edge UA(不带 Headless 字样,版本与本机 Edge 一致)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0")

EXCLUDE_COMMON = ["ptfe", "涂层", "coated", "铝箔", "foil", "胶带", "tape",
                  "高硅", "silica", "网格", "mesh", "清洁", "wiper", "抹布",
                  "毛巾", "抛光", "导电", "防静电", "anti-static", "esd",
                  "碳纤", "carbon", "手套", "glove", "帐篷", "tent", "过滤", "filter",
                  # 2026-10-11 净化升级:G75 池曾混入建材级 E 玻璃纱(用于石膏加固/
                  # 建筑补强/船用),把中位从 ~10.6 元/kg 拖到 6.7,见 rebuild_b2b.py
                  "石膏", "gypsum", "plaster", "加固", "reinforc",
                  "建材", "建筑", "building", "construct",
                  "船用", "boat", "marine", "冲浪", "surf", "墙体"]

# (搜索词, 展示名, 标题必含token, 标题必含任一, 聚合单位, 价格下限, 价格上限)
KEYWORDS = [
    ("7628 electronic glass fiber cloth", "7628 电子布", ["7628"],
     ["电子", "pcb", "ccl", "electronic", "e-glass", "e glass", "e玻璃"], "㎡", 1.0, 150.0),
    ("1080 glass fiber fabric electronic", "1080 薄布", ["1080"],
     ["电子", "pcb", "ccl", "electronic", "e-glass", "e glass"], "㎡", 0.5, 120.0),
    ("2116 glass fiber fabric electronic", "2116 薄布", ["2116"],
     ["电子", "pcb", "ccl", "electronic", "e-glass", "e glass"], "㎡", 0.5, 120.0),
    ("G75 electronic glass fiber yarn", "G75 电子纱", ["g75"],
     ["yarn", "纱", "电子", "electronic"], "kg", 2.0, 200.0),
    ("FR-4 copper clad laminate sheet", "FR-4 覆铜板", ["fr-4", "fr4"],
     ["copper clad", "覆铜板", "ccl", "laminate"], "张", 3.0, 2000.0),
]

RE_TITLE = re.compile(
    r'<h2 class="searchx-product-e-title"[^>]*>\s*<a[^>]*>\s*<span>([^<]+)</span>', re.S)
RE_PID = re.compile(r'product-detail/[^"\']*?_(\d{8,})\.html')
RE_PRICE = re.compile(r'searchx-product-price-price-main">([^<]{1,40})<')
RE_MOQ = re.compile(r'最低起订量：\s*([^<]{1,60})<')
RE_SUP = re.compile(r'class="searchx-product-e-company"[^>]*>([^<]{1,120})<')
RE_NUM = re.compile(r"([0-9][0-9,.]*)\s*(.*)")


def _norm_unit(u: str) -> str:
    u = u.strip().lower()
    if "square meter" in u or "㎡" in u or "m²" in u:
        return "㎡"
    if u in ("piece", "pieces", "sheet", "sheets", "pc", "pcs"):
        return "张"
    if u in ("kilogram", "kilograms", "kg"):
        return "kg"
    if u in ("ton", "tons", "metric ton", "metric tons"):
        return "ton"
    if u in ("meter", "meters", "m"):
        return "m"
    if "roll" in u:
        return "roll"
    return u


def _parse_price(s: str):
    """'¥57.34-115.34' → (mid, 'CNY');'US $3.20' → (3.2,'USD')。解析失败 None。"""
    s = s.strip()
    if s.startswith("¥") or s.startswith("￥"):
        cur = "CNY"
        body = s.lstrip("¥￥").strip()
    elif s.lower().startswith("us"):
        cur = "USD"
        body = re.sub(r"^(us\s*\$)\s*", "", s, flags=re.I)
    else:
        return None
    body = body.replace(",", "")
    parts = [p for p in re.split(r"[-–~]", body) if p]
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return None
    return (sum(vals) / len(vals), cur)


def parse_search(html: str, cfg) -> list[dict]:
    """(query, name, must, must_any, agg_unit, lo, hi) → 过滤后的挂牌行。"""
    query, name, must, must_any, agg_unit, lo, hi = cfg
    heads = list(RE_TITLE.finditer(html))
    rows, seen = [], set()
    for i, m in enumerate(heads):
        title = m.group(1).strip()
        seg = html[m.start(): heads[i + 1].start() if i + 1 < len(heads) else len(html)]
        low = title.lower()
        if not any(t in low for t in must):
            continue
        if not any(t in low for t in must_any):
            continue
        if any(t in low for t in EXCLUDE_COMMON):
            continue
        pm = RE_PRICE.search(seg)
        moqm = RE_MOQ.search(seg)
        supm = RE_SUP.search(seg)
        pidm = RE_PID.search(seg)
        if not pm or not moqm:
            continue
        pp = _parse_price(pm.group(1))
        if not pp:
            continue
        price, cur = pp
        moq_txt = moqm.group(1).strip()
        nm = RE_NUM.match(moq_txt)
        unit = _norm_unit(nm.group(2)) if nm else ""
        rows.append({
            "keyword": name, "title": title,
            "supplier": supm.group(1).strip() if supm else "",
            "price": round(price, 4), "currency": cur, "unit": unit,
            "moq": moq_txt, "url": "https://www.alibaba.com/product-detail/"
            + (pidm.group(1) if pidm else "unknown") + ".html",
        })
    # 同 url 去重(轮播重复)
    uniq = {}
    for r in rows:
        uniq.setdefault(r["url"], r)
    out = []
    for r in uniq.values():
        if r["currency"] != "CNY":
            continue
        if r["unit"] == "ton":            # 吨价折算成 kg 价
            r = {**r, "price": round(r["price"] / 1000.0, 4), "unit": "kg"}
        if not (lo <= r["price"] <= hi):
            continue
        out.append(r)
    return out


def _aggregate(rows: list[dict], unit: str):
    ps = sorted(r["price"] for r in rows if r["unit"] == unit)
    if not ps:
        return None
    n = len(ps)
    pick = lambda q: ps[min(n - 1, int(round(q * (n - 1))))]
    return {"n": n, "p25": pick(0.25), "median": statistics.median(ps),
            "p75": pick(0.75), "unit": unit}


def _flagged() -> bool:
    """熔断期内(最近一次验证码在 COOLDOWN_DAYS 内)则跳过抓取。"""
    if not FLAG.exists():
        return False
    try:
        d = json.loads(FLAG.read_text())["last_captcha"]
        age = (tz.today() - dt.date.fromisoformat(d)).days
        return age < COOLDOWN_DAYS
    except Exception:
        return False


def _set_flag():
    FLAG.parent.mkdir(parents=True, exist_ok=True)
    FLAG.write_text(json.dumps({"last_captcha": tz.today().isoformat()}))


def unlock(timeout_s: int = 300) -> bool:
    """人工兜底:弹 Edge 打开被拦的搜索页,人工拖一次滑块(无账号无个人信息),
    通过后 anti-bot cookie 存 STATE 供 headless 复用(UA 与 fetch 端一致)。"""
    from urllib.parse import quote

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=False,
                               args=["--disable-blink-features=AutomationControlled"],
                               ignore_default_args=["--enable-automation"])
        ctx = b.new_context(user_agent=UA, locale="zh-CN",
                            viewport={"width": 1366, "height": 850})
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        pg = ctx.new_page()
        pg.goto("https://www.alibaba.com/trade/search?SearchText="
                + quote("7628 electronic glass fiber cloth"),
                wait_until="domcontentloaded", timeout=45000)
        print("Edge 已打开:请拖动滑块完成验证(无需登录任何账号)...", flush=True)
        ok = False
        try:
            for _ in range(timeout_s // 5):
                pg.wait_for_timeout(5000)
                try:
                    h = pg.content()
                    if h.count("¥") + h.count("￥") >= 3 \
                            and "searchx-product-e-title" in h:
                        ok = True
                        break
                except Exception:
                    pass
        except Exception as e:
            if "TargetClosed" in type(e).__name__ or "closed" in str(e).lower():
                print("窗口被手动关闭,未保存。")
                return False
            raise
        if ok:
            ctx.storage_state(path=str(STATE))
            # 验证通过即解除熔断
            if FLAG.exists():
                FLAG.unlink()
            print("验证通过,anti-bot cookie 已存 ->", STATE)
        else:
            print("超时未检测到通过。")
        b.close()
        return ok


def _grabber():
    """启动 headless 浏览器,带 STATE(若有)。返回 (pw, browser, page, stop)。"""
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()
    b = p.chromium.launch(channel="msedge", headless=True,
                          args=["--disable-blink-features=AutomationControlled"],
                          ignore_default_args=["--enable-automation"])
    kw = dict(user_agent=UA, locale="zh-CN", viewport={"width": 1366, "height": 850})
    ctx = b.new_context(storage_state=str(STATE)) if STATE.exists() \
        else b.new_context(**kw)
    if STATE.exists():  # storage_state 后补 UA/视口属性
        pass
    ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
    pg = ctx.new_page()
    return p, b, pg, p.stop


def fetch_all(day: str):
    """抓全部关键词,返回 (listings, dailies, warns)。熔断期内直接空手而归。"""
    from urllib.parse import quote

    if _flagged():
        return [], [], [f"熔断冷却中(上次验证码 {_flagged_date()},跳过今日)"]

    listings, dailies, warns = [], [], []
    p, b, pg, stop = _grabber()
    try:
        # 首页预热:拿正常 cookie 再进搜索
        try:
            pg.goto("https://www.alibaba.com/", wait_until="domcontentloaded",
                    timeout=45000)
            pg.wait_for_timeout(5000)
        except Exception:
            pass
        SNAP.mkdir(parents=True, exist_ok=True)
        for cfg in KEYWORDS:
            query, name = cfg[0], cfg[1]
            try:
                pg.goto("https://www.alibaba.com/trade/search?SearchText="
                        + quote(query), wait_until="domcontentloaded",
                        timeout=45000)
                pg.wait_for_timeout(8000)
            except Exception as e:
                warns.append(f"{name}: goto {type(e).__name__}")
                continue
            html = pg.content()
            if "验证码拦截" in html or "punish" in html:
                _set_flag()
                warns.append("命中验证码→熔断冷却,今日放弃(详见 ali.py 注释)")
                listings, dailies = [], []
                break
            (SNAP / f"latest_{name.replace(' ', '_').replace('/', '_')}.html") \
                .write_text(html, encoding="utf-8", errors="ignore")
            rows = parse_search(html, cfg)
            if not rows and html.count("¥") + html.count("￥") < 3:
                warns.append(f"{name}: 0挂牌(页面异常),见快照")
                continue
            now = tz.now().isoformat(timespec="seconds")
            for r in rows:
                r["date"] = day
                r["fetched_at"] = now
            listings.extend(rows)
            agg = _aggregate(rows, cfg[4])
            if agg:
                agg.update({"keyword": name, "date": day, "fetched_at": now})
                dailies.append(agg)
            else:
                warns.append(f"{name}: 过滤后 {len(rows)} 条但无 {cfg[4]} 单位可聚合")
            time.sleep(5)
    finally:
        b.close()
        stop()
    return listings, dailies, warns


def _flagged_date() -> str:
    try:
        return json.loads(FLAG.read_text())["last_captcha"]
    except Exception:
        return "?"


if __name__ == "__main__":
    import sys

    from . import store

    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if cmd == "unlock":
        sys.exit(0 if unlock() else 1)
    elif cmd == "fetch":
        day = tz.today().isoformat()
        listings, dailies, warns = fetch_all(day)
        con = store.connect(DB)
        by_kw = {}
        for r in listings:
            by_kw.setdefault(r["keyword"], []).append(r)
        for d in dailies:
            store.replace_b2b(con, day, d["keyword"],
                              by_kw.get(d["keyword"], []), d)
        con.close()
        print(f"[{day}] listings={len(listings)} dailies={len(dailies)}")
        for w in warns:
            print("  WARN:", w)
        for d in dailies:
            print(f"  {d['keyword']}: n={d['n']} med={d['median']} "
                  f"[{d['p25']}~{d['p75']}] {d['unit']}")
