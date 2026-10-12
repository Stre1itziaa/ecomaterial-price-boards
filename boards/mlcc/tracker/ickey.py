"""云汉芯城（ickey.cn）MLCC 报价抓取：纯 requests，解析搜索页 JSON-LD。

口径：起订档单价（Offer.price，CNY）+ 精确库存（inventoryLevel.value）
+ 最小起订量（eligibleTransactionVolume.minPrice）。
料号按 name 尾词精确匹配，避免同系列干扰。
"""

from . import tz
import pathlib
import re
import time
from dataclasses import dataclass, field

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
URL = "https://www.ickey.cn/search?keyword={pn}"


@dataclass
class Quote:
    source: str = "ICKey"
    part: str = ""
    brand: str = ""
    seg: str = ""            # 品类段：高容/中容/低容/车规
    desc: str = ""
    date: str = ""           # 抓取日（云汉页面不带数据日期）
    price: float = 0.0       # 起订档单价 CNY
    stock: int = 0           # 库存
    moq: int = 0             # 最小起订量
    currency: str = "CNY"
    extra: dict = field(default_factory=dict)


def fetch_part(pn: str, brand: str, seg: str, desc: str, today: str,
               session: requests.Session, retries: int = 3) -> Quote | None:
    last = None
    for i in range(1, retries + 1):
        try:
            r = session.get(URL.format(pn=pn), timeout=30,
                            headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
            r.raise_for_status()
            if len(r.content) < 5_000:
                raise RuntimeError(f"页面过小({len(r.content)}B)，疑似拦截")
            return parse(pn, brand, seg, desc, today, r.text)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * i)
    print(f"[ickey] {pn} 抓取失败: {last}")
    return None


def parse(pn: str, brand: str, seg: str, desc: str, today: str, html: str) -> Quote | None:
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    if not m:
        return None
    import json
    try:
        ld = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    prods = ld.get("hasPart", {}).get("itemListElement", [])
    # 精确匹配：name 以料号结尾
    for p in prods:
        name = (p.get("name") or "").strip()
        if not name.endswith(pn):
            continue
        offers = p.get("offers") or []
        off = offers[0] if offers else None
        if not off or off.get("availability", "").endswith("OutOfStock"):
            return None
        stock_raw = ((off.get("inventoryLevel") or {}).get("value")) or 0
        moq_raw = ((off.get("eligibleTransactionVolume") or {}).get("minPrice")) or 0
        return Quote(
            part=pn, brand=brand, seg=seg, desc=name, date=today,
            price=float(off["price"]), stock=int(float(stock_raw)),
            moq=int(float(moq_raw)),
            extra={"page_name": name[:80]},
        )
    return None


def crawl(snapshot_dir: pathlib.Path, parts, today: str, pause: float = 6.0):
    """parts: tracker.parts.PARTS。返回 Quote 列表。

    实测：连续快请求会触发限流（返回精简页无 JSON-LD），
    间隔 6s + 失败退避 15s 重试可稳定通过。16 料号约 2 分钟。
    """
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    out = []
    import json as _json
    for pn, brand, seg, desc in parts:
        q = fetch_part(pn, brand, seg, desc, today, s, retries=2)
        if not q:  # 限流退避后单补两次
            for wait in (15, 25):
                time.sleep(wait)
                q = fetch_part(pn, brand, seg, desc, today, s, retries=1)
                if q:
                    break
        if q:
            out.append(q)
        else:
            print(f"[ickey] {pn} 无精确匹配/无货/限流，跳过")
        time.sleep(pause)
    stamp = today.replace("-", "")
    (snapshot_dir / f"ickey_{stamp}.jsonl").write_text(
        "\n".join(_json.dumps(q.__dict__, ensure_ascii=False) for q in out), encoding="utf-8")
    return out
