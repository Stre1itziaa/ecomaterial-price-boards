"""立创商城（szlcsc.com）MLCC 报价抓取。

通道：Playwright headless（HTTP 层反爬 203）→ 渲染页内嵌 __NEXT_DATA__ JSON。
数据路径：props.pageProps.soData.searchResult.productRecordList[*].productVO
  - productModel 精确匹配料号（搜索是模糊的，同系列会混入）
  - productPriceList: [{startPurchasedNumber, productPrice}] 完整阶梯
  - stockNumber: 精确库存
口径：第一档单价为主口径，全阶梯入 extra。
"""
from . import tz
import json
import pathlib
import re
import time

from playwright.sync_api import sync_playwright

from .ickey import Quote

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
URL = "https://so.szlcsc.com/global.html?k={pn}"
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def parse(pn: str, brand: str, seg: str, desc: str, today: str, html: str) -> Quote | None:
    m = NEXT_RE.search(html)
    if not m:
        return None
    try:
        nd = json.loads(m.group(1))
        records = nd["props"]["pageProps"]["soData"]["searchResult"]["productRecordList"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    for rec in records or []:
        vo = rec.get("productVO") or {}
        if (vo.get("productModel") or "").strip() != pn:
            continue
        ladder = sorted(
            [(p["startPurchasedNumber"], float(p["productPrice"]))
             for p in vo.get("productPriceList") or [] if p.get("productPrice")],
            key=lambda x: x[0])
        if not ladder:
            return None
        first_qty, first_price = ladder[0]
        return Quote(
            source="LCSC", part=pn, brand=brand, seg=seg,
            desc=(vo.get("productName") or desc)[:80], date=today,
            price=first_price, stock=int(vo.get("stockNumber") or 0),
            moq=int(vo.get("minBuyNumber") or first_qty),
            extra={"ladder": ladder, "valid_stock": vo.get("validStockNumber")},
        )
    return None


STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
window.chrome = window.chrome || {runtime: {}};
"""


def crawl(snapshot_dir: pathlib.Path, parts, today: str, pause: float = 9.0):
    """每料号新开 browser context（连续同 context 抓取会触发风控，
    实测第 3 个起全空），加 stealth 脚本与随机间隔。16 料号约 3 分钟。"""
    import random
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    out = []
    stamp = today.replace("-", "")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for idx, (pn, brand, seg, desc) in enumerate(parts):
            ctx = browser.new_context(
                user_agent=UA,
                viewport={"width": 1380 + random.randint(0, 80),
                          "height": 860 + random.randint(0, 60)},
                locale="zh-CN",
            )
            ctx.add_init_script(STEALTH_JS)
            page = ctx.new_page()
            page.set_default_timeout(45000)
            try:
                page.goto(URL.format(pn=pn), timeout=60000)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(3500)
                html = page.content()
                (snapshot_dir / f"lcsc_{stamp}_{pn}.html").write_text(html, encoding="utf-8")
                q = parse(pn, brand, seg, desc, today, html)
                if q:
                    out.append(q)
                else:
                    print(f"[lcsc] {pn} 精确无货/无匹配，跳过")
            except Exception as e:  # noqa: BLE001
                print(f"[lcsc] {pn} 失败: {e}")
            finally:
                ctx.close()
            if idx < len(parts) - 1:
                time.sleep(pause + random.uniform(0, 3))
        browser.close()
    return out
