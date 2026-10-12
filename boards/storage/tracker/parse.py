"""解析 TrendForce 中文站价格页 HTML -> 结构化行情行。

页面结构（2026-09 现状）：
- 每个类目族一个页面（dram / flash），页内按文档顺序排多个板块表格；
- 每个表格上方紧邻一个 `更新日期 YYYY-MM-DD HH:MM (GMT+8)` 的 <p>；
- 免费页部分板块只有产品名 chips 无数值（LPDDR现货、Mobile DRAM合约、
  eMMC现货、eMMC/UFS合约、Wafer合约），自动跳过。
"""
from . import tz
import datetime as dt
import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# 各页面按文档顺序出现的数据表（有数值的）。顺序即页面上板块出现顺序。
SECTIONS = {
    "dram": [
        ("DRAM", "现货价"),
        ("DRAM", "合约价"),
        ("Module", "现货价"),
        ("GDDR", "现货价"),
    ],
    "flash": [
        ("NAND", "现货价"),
        ("NAND", "合约价"),
        ("Wafer", "现货价"),
        ("Memory Card", "现货价"),
        ("SSD", "合约价"),
        ("SSD", "市场价"),
    ],
}

DATE_RE = re.compile(r"更新日期\s*(\d{4}-\d{2}-\d{2})")
NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
SKIP_RE = re.compile(r"updated on|click here", re.I)


@dataclass
class QuoteRow:
    family: str
    section: str
    name: str
    vendors: str
    unit: str
    date: str          # 数据日期 YYYY-MM-DD（页面自带的更新日期）
    high: float | None
    low: float | None
    avg: float
    change_pct: float | None
    extra: dict
    source: str = "TrendForce"   # 数据商：TrendForce / CFM
    freq: str = "daily"          # daily / weekly / monthly / index


def _f(cell) -> float | None:
    t = cell.get_text(" ", strip=True).replace(",", "")
    return float(t) if NUM_RE.match(t) else None


def _change(cell) -> float | None:
    """'▲ 0.73 %'->0.73  '▼ -2.71 %'->-2.71  '— 0.00 %'->0.0"""
    t = cell.get_text(" ", strip=True)
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    if not m:
        return None
    val = float(m.group())
    if val > 0 and "▼" in t:
        val = -val
    return val


def _rows_with_dates(soup):
    """按文档位置交替返回 [(table, date_or_None)]，date 取表格上方最近的更新日期。"""
    events = []
    for p in soup.find_all("p"):
        m = DATE_RE.search(p.get_text())
        if m:
            events.append((p.sourceline or 0, "date", m.group(1)))
    for t in soup.find_all("table"):
        events.append((t.sourceline or 0, "table", t))
    events.sort(key=lambda e: e[0])
    cur_date = None
    out = []
    for _, kind, payload in events:
        if kind == "date":
            cur_date = payload
        else:
            out.append((payload, cur_date))
    return out


def _cells(tr):
    return tr.find_all("td")


def _parse_row(tr, family, section, date):
    cells = _cells(tr)
    if len(cells) < 2:
        return None
    name_span = cells[0].find("span")
    name = cells[0].get_text(" ", strip=True)
    if not name or SKIP_RE.search(name):
        return None
    vendors = (name_span.get("title") or "").strip() if name_span else ""
    # nums[k] 对应 cells[k+1]
    nums = [_f(c) for c in cells[1:]]

    if section == "市场价":  # 品牌|规格|系列|容量|高点|低点|均价|涨跌幅|走势图
        if len(cells) < 8 or nums[5] is None:
            return None
        brand, spec, series, cap = (c.get_text(" ", strip=True) for c in cells[:4])
        name = f"{brand} {series} {cap} ({spec})".replace("  ", " ")
        return QuoteRow(family, section, name, vendors, "USD", date,
                        nums[3], nums[4], nums[5], _change(cells[7]) if len(cells) > 7 else None,
                        {"brand": brand, "spec": spec, "series": series, "capacity": cap})

    if len(cells) >= 6 and nums[3] is not None:  # 日/周高点|日/周低点|盘高|盘低|盘均|涨跌幅|走势图
        period = "周" if "周高点" in cells[1].get_text() else "日"
        return QuoteRow(family, section, name, vendors, "USD", date,
                        nums[2], nums[3], nums[4],
                        _change(cells[6]) if len(cells) > 6 else None,
                        {"period_high": nums[0], "period_low": nums[1], "period": period})
    if len(cells) >= 4 and nums[2] is not None:  # 高点|低点|均价|均价涨跌|低点涨跌|走势图
        extra = {}
        if len(cells) > 5:
            extra["low_change_pct"] = _change(cells[5])
        return QuoteRow(family, section, name, vendors, "USD", date,
                        nums[0], nums[1], nums[2],
                        _change(cells[4]) if len(cells) > 4 else None, extra)
    return None


def parse_page(page_key: str, html: str) -> list[QuoteRow]:
    soup = BeautifulSoup(html, "html.parser")
    dated = _rows_with_dates(soup)
    today = tz.now().strftime("%Y-%m-%d")
    # 只取带数值单元格的数据表，按文档顺序与 SECTIONS[page_key] 一一对应
    data_tables = []
    for t, date in dated:
        has_num = any(NUM_RE.match(c.get_text(" ", strip=True).replace(",", ""))
                      for tr in t.find_all("tr") for c in _cells(tr)[1:])
        if has_num:
            data_tables.append((t, date or today))
    expected = SECTIONS[page_key]
    if len(data_tables) != len(expected):
        print(f"[warn] {page_key} 页数据表数 {len(data_tables)} != 预期 {len(expected)}，按顺序对齐")
    rows = []
    for (t, date), (family, section) in zip(data_tables, expected):
        for tr in t.find_all("tr"):
            r = _parse_row(tr, family, section, date)
            if r:
                rows.append(r)
    return rows


def parse_snapshots(pages: dict[str, str]) -> list[QuoteRow]:
    all_rows = []
    for key, html in pages.items():
        for r in parse_page(key, html):
            r.freq = {"现货价": "daily", "合约价": "monthly", "市场价": "weekly"}.get(r.section, "daily")
            all_rows.append(r)
    # 去重：同板块同名产品同日期保留一条
    seen, uniq = set(), []
    for r in all_rows:
        k = (r.family, r.section, r.name, r.date)
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def row_extra_json(r: QuoteRow) -> str:
    return json.dumps(r.extra, ensure_ascii=False) if r.extra else None
