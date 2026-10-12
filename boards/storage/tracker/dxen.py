"""DRAMeXchange 英文站首页现货表 —— TrendForce 免费中文页停更板块的救援源。

背景（2026-10-05 实测）：trendforce.cn 免费页合约价板块更新日期停在 2026-08-31，
SLC/MLC/GDDR/晶圆/MicroSD 等现货小节停在 2026-09-21（页面自身停更，非解析故障）；
dramexchange.com 英文首页免费表仍在更新同一批品种，且纯 HTML 无反爬。

页面结构（7 张带数值的表）：
- 现货表：Item | Daily/Weekly High | Daily/Weekly Low | Session High | Session Low
  | Session Average | Session Change | History → 5 个纯数值格，涨跌格含 % 非纯数值
- 品牌 SSD 表：Brand | Interface | Series | Capacity | High | Low | Avg. | Change
  → 数值格从第 5 格起，共 3 个

救援策略（历史必须真实）：
- 只对回库内已存在的 TrendForce 产品（归一化名称=压缩连续空白后精确匹配），
  不新建产品、不碰合约价（已退役）；
- 英文页不带数据日期，语义=最新 session，落库用抓取日；
- high/low/avg 与库内最新一行完全一致时跳过，不制造虚假日更；
- change_pct 一律置空：skip-unchanged 语义下相邻库行并非页面意义上的相邻
  session，带涨跌幅会污染「TF 涨跌幅与前值自洽」审计。
"""
from . import tz
import datetime as dt
import pathlib
import re
import time

from bs4 import BeautifulSoup

from .parse import QuoteRow

URL = "https://www.dramexchange.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def fetch_home(snapshot_dir: pathlib.Path, retries: int = 3, pause: float = 2.0) -> str:
    import requests
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(URL, headers={"User-Agent": UA,
                                           "Accept-Language": "en-US,en;q=0.9"}, timeout=30)
            r.raise_for_status()
            if len(r.content) < 100_000:
                raise RuntimeError(f"页面过小({len(r.content)}B)，疑似拦截或改版")
            path = snapshot_dir / f"{tz.now():%Y%m%d}_dxi_en.html"
            path.write_text(r.text, encoding="utf-8")
            return r.text
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(pause * attempt)
    raise RuntimeError(f"抓取 {URL} 失败(重试{retries}次): {last}")


def parse_home(html: str) -> list[dict]:
    """返回 [{"kind": "spot"|"brand", "name": str, "high","low","avg": float}]，同 kind+name 去重。"""
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 6:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            if _norm(texts[0]).lower() in ("item", "brand"):
                continue
            num_idx = [i for i, t in enumerate(texts) if NUM_RE.match(t.replace(",", ""))]
            if len(num_idx) == 5 and num_idx[0] == 1:
                # 现货行：格1-2=日/周高·低，格5=盘均（格6 涨跌含 %，格7 走势图）
                kind, name = "spot", _norm(texts[0])
                high, low, avg = (float(texts[i].replace(",", "")) for i in (1, 2, 5))
            elif len(num_idx) == 3 and num_idx[0] == 4:
                # 品牌 SSD 行：Brand|Interface|Series|Capacity|High|Low|Avg
                brand, iface, series, cap = (re.sub(r"\s+", " ", t) for t in texts[:4])
                kind = "brand"
                name = _norm(f"{brand} {series} {cap} ({iface})".replace("  ", " "))
                high, low, avg = (float(texts[i].replace(",", "")) for i in (4, 5, 6))
            else:
                continue
            if not name or (kind, name) in seen:
                continue
            seen.add((kind, name))
            out.append({"kind": kind, "name": name, "high": high, "low": low, "avg": avg})
    return out


def product_index(con) -> dict[str, dict]:
    """库内 TrendForce 现货/市场价产品 → 归一化名索引，附最新一行行情供跳重判断。"""
    idx: dict[str, dict] = {}
    for p in con.execute(
            "SELECT id, family, section, name, vendors, unit, freq FROM products "
            "WHERE source='TrendForce' AND section IN ('现货价','市场价')").fetchall():
        idx[_norm(p["name"])] = dict(p)
    for p in idx.values():
        last = con.execute(
            "SELECT high, low, avg FROM quotes WHERE product_id=? "
            "ORDER BY date DESC LIMIT 1", (p["id"],)).fetchone()
        p["last"] = tuple(last) if last else None
    return idx


def crawl(snapshot_dir: pathlib.Path, con, today: str) -> list[QuoteRow]:
    html = fetch_home(snapshot_dir)
    items = parse_home(html)
    idx = product_index(con)
    rows, rescued, skipped, unmatched = [], 0, 0, 0
    for item in items:
        p = idx.get(item["name"])
        if not p:
            unmatched += 1
            continue  # 救援腿不新建产品
        triple = (item["high"], item["low"], item["avg"])
        if p["last"] and all(abs(a - b) < 1e-9 for a, b in zip(triple, p["last"])):
            skipped += 1
            continue
        rows.append(QuoteRow(
            family=p["family"], section=p["section"], name=p["name"],
            vendors=p["vendors"], unit=p["unit"] or "USD", date=today,
            high=item["high"], low=item["low"], avg=item["avg"], change_pct=None,
            extra={"via": "DXI-EN"}, source="TrendForce", freq=p["freq"] or "weekly"))
        rescued += 1
    print(f"[dxen] 英文首页 {len(items)} 行 → 救援 {rescued}，同值跳过 {skipped}，"
          f"未匹配 {unmatched}（不新建）")
    return rows
