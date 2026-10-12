"""Mouser 中国站（mouser.cn）MLCC 参照报价：Playwright headless。

通道：裸 requests 连打 4~5 次触发 DataDome 403；headless Chromium 首屏会拿到
JS 挑战页（~1.5KB），challenge 自动解开并重载（实测 10~25s），轮询等重载即可，
无需真浏览器窗口（schtasks 隐藏启动纪律：不得弹窗）。

数据路径：页面内 schema.org Product JSON-LD
  - mpn 精确匹配料号；单一命中时 /c/?q= 直接 302 到详情页
  - offers.price = 单件挂牌价（priceCurrency=RMB），inventoryLevel = 库存
  - offers.availability = InStock / OutOfStock

口径：Mouser 单件挂牌价 ≠ 立创"起订档单价"（系统性偏高，量大档差数倍），
仅作缺货料号的独立参照价，不与立创/云汉混算、不入双源价差对照。
"""

from . import tz
import json
import pathlib
import random
import re
import time

from playwright.sync_api import sync_playwright

from .ickey import Quote

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SEARCH_URL = "https://www.mouser.cn/c/?q={pn}"
DETAIL_URL = "https://www.mouser.cn{href}"
CHALLENGE_MARK = "Please enable JS"
MIN_OK_SIZE = 20_000


def _wait_page(page, timeout_s: int = 45) -> str | None:
    """轮询等 DataDome 挑战重载；拿到真实页返回 HTML，超时返回 None。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        html = page.content()
        if len(html) > MIN_OK_SIZE and CHALLENGE_MARK not in html:
            return html
        page.wait_for_timeout(3000)
    return None


def _extract_product(pn: str, html: str) -> dict | None:
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product" \
                and (d.get("mpn") or "").upper() == pn.upper():
            return d
    return None


def _parse_offer(pn: str, brand: str, seg: str, desc: str, today: str,
                 prod: dict) -> Quote:
    off = prod.get("offers") or {}
    oos = (off.get("availability") or "").endswith("OutOfStock")
    return Quote(
        source="Mouser", part=pn, brand=brand, seg=seg,
        desc=(prod.get("description") or desc)[:80], date=today,
        price=float(off["price"]),
        stock=int(off.get("inventoryLevel") or 0),
        moq=1,  # Mouser 单件起售
        extra={"availability": "OutOfStock" if oos else "InStock",
               "currency": off.get("priceCurrency"),
               "caliber": "单件挂牌价（非起订档，勿与立创/云汉比价）"},
    )


def fetch_part(pn: str, brand: str, seg: str, desc: str, today: str,
               ctx) -> tuple[Quote | None, str | None]:
    """返回 (Quote|None, html|None)。html 无论成败都返回，供快照留痕。"""
    page = ctx.new_page()
    page.set_default_timeout(60000)
    html = None
    try:
        page.goto(SEARCH_URL.format(pn=pn), timeout=60000,
                  wait_until="domcontentloaded")
        html = _wait_page(page)
        if html is None:
            print(f"[mouser] {pn} DataDome 挑战未通过/超时")
            return None, None
        prod = _extract_product(pn, html)
        if prod is None:
            # 单一命中时 /c/?q= 已 302 到详情页（无 ProductDetail 链接但有 ld+json）；
            # 多结果搜索页：进入含料号的详情页再取
            links = [h for h in re.findall(r'href="(/zh/ProductDetail/[^"]+)"', html)
                     if pn.lower() in h.lower()]
            if links:
                page.goto(DETAIL_URL.format(href=links[0]), timeout=60000,
                          wait_until="domcontentloaded")
                html = _wait_page(page)
                if html is None:
                    print(f"[mouser] {pn} 详情页加载超时")
                    return None, None
                prod = _extract_product(pn, html)
            if prod is None:
                # 详情页存在但无 Product Offer = Mouser 未备该料（页面只剩相似品推荐），
                # 属真实无报价，不是抓取失败
                if "/ProductDetail/" in page.url or "GRM" in html[:4000]:
                    print(f"[mouser] {pn} Mouser 无报价（无 Offer JSON-LD，疑似不备货）")
                else:
                    print(f"[mouser] {pn} 搜索页无精确命中")
            return (None if prod is None else _parse_offer(pn, brand, seg, desc, today, prod),
                    html)
        return _parse_offer(pn, brand, seg, desc, today, prod), html
    except Exception as e:  # noqa: BLE001
        print(f"[mouser] {pn} 失败: {e}")
        return None, html
    finally:
        page.close()


def crawl(snapshot_dir: pathlib.Path, parts, today: str, pause: float = 20.0):
    """parts: [(料号, 品牌, 品类段, 描述)] 子集。DataDome 通过是概率性的：
    挑战未解则丢弃 context 全新重试（最多 3 次）；料号间固定间隔。"""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    out = []
    stamp = today.replace("-", "")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for idx, (pn, brand, seg, desc) in enumerate(parts):
            q, html = None, None
            for attempt in range(1, 4):
                ctx = browser.new_context(
                    user_agent=UA,
                    viewport={"width": 1400 + random.randint(0, 60),
                              "height": 880 + random.randint(0, 50)},
                    locale="zh-CN",
                )
                ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                    "Object.defineProperty(navigator,'languages',{get:()=>['zh-CN','zh','en']});"
                    "window.chrome=window.chrome||{runtime:{}};")
                try:
                    q, html = fetch_part(pn, brand, seg, desc, today, ctx)
                finally:
                    ctx.close()
                if q:
                    break
                if html is None and attempt < 3:
                    print(f"[mouser] {pn} 第 {attempt} 次挑战失败，换 context 重试")
                    time.sleep(15 + random.uniform(0, 10))
            if html is not None:
                (snapshot_dir / f"mouser_{stamp}_{pn}.html").write_text(
                    html, encoding="utf-8")
            if q:
                out.append(q)
                print(f"[mouser] {pn} ¥{q.price} 库存{q.stock} {q.extra['availability']}")
            else:
                print(f"[mouser] {pn} 跳过")
            if idx < len(parts) - 1:
                time.sleep(pause + random.uniform(0, 5))
        browser.close()
    if out:
        (snapshot_dir / f"mouser_{stamp}.jsonl").write_text(
            "\n".join(json.dumps(q.__dict__, ensure_ascii=False) for q in out),
            encoding="utf-8")
    return out
