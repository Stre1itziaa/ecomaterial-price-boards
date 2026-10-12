"""玻纤周评方向层(周频):卓创 + 百川免费频道页,抓周评标题。

数据形态=周评标题(方向语义,无数字):两站频道页公开可直连(curl 实测 200),
无登录无验证码。标题全文入库带原文链接;direction() 只做展示标签,
不产生任何数值,不与锚点/B2B 价格层混算。
- 卓创 nonmetal.sci99.com/product/glass_fiber 「玻璃纤维周评」,标题自带周期区间;
- 百川 baiinfo.com/xianweicailiao/bolixianwei 「周评:…」,日期在链接旁 time 单元格。
"""

from . import tz
import datetime as dt
import re
import urllib.request

SCI99_URL = "https://nonmetal.sci99.com/product/glass_fiber"
BAIINFO_URL = "https://www.baiinfo.com/xianweicailiao/bolixianwei"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 fabric-weekly/1.0")

# 方向标签(仅展示):按电子纱分句后的语义词匹配,宁缺毋滥
_DIR_RULES = [
    (r"上涨|提涨|跳涨|涨价|涨幅|新高", "涨"),
    (r"下跌|回落|走低|降价", "跌"),
    (r"暂稳|持稳|平稳|稳中|弱稳|稳定", "稳"),
]


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def _md_to_iso(md: str, today: dt.date) -> str:
    """频道页日期只带 MM-DD;年初看到去年 12 月的条目时回退一年。"""
    d = dt.date(today.year, int(md[:2]), int(md[3:5]))
    if d > today:
        d = d.replace(year=today.year - 1)
    return d.isoformat()


def fetch(today: dt.date | None = None) -> list[dict]:
    today = today or tz.today()
    out = []

    html = _get(SCI99_URL)
    for m in re.finditer(
            r'href="(https://nonmetal\.sci99\.com/info/[^"]+)"[^>]*'
            r'title="(玻璃纤维周评[^"]+)"', html):
        url, title = m.group(1), m.group(2)
        # 周期格式:（YYYYMMDD-MMDD)如 20260918-0924=9/18~9/24;取期末为该周锚
        pm = re.search(r"（(\d{4})(\d{4})-(\d{4})）", title)
        if not pm:
            continue
        year, md0, md1 = pm.group(1), pm.group(2), pm.group(3)
        if md1 < md0:  # 跨年周期(如 20261228-0103)
            year = str(int(year) + 1)
        out.append({"date": f"{year}-{md1[:2]}-{md1[2:]}",
                    "src": "卓创资讯", "title": title, "url": url})

    html = _get(BAIINFO_URL)
    for m in re.finditer(
            r'href="(/news/6525/\d+/oi)"[^>]*>(周评：[^<]+)</a>.{0,800}?'
            r'class="time[^"]*"[^>]*>(\d{2}-\d{2})', html, re.S):
        path, title, md = m.group(1), m.group(2), m.group(3)
        out.append({"date": _md_to_iso(md, today), "src": "百川盈孚",
                    "title": title, "url": "https://www.baiinfo.com" + path})

    seen, rows = set(), []
    for r in out:
        k = (r["date"], r["src"], r["title"])
        if k not in seen:
            seen.add(k)
            rows.append(r)
    return rows


def direction(title: str) -> str:
    """从周评标题提电子纱/电子布方向标签(仅展示,非数值)。"""
    seg = title.split("电子纱")[-1] if "电子纱" in title else title
    for pat, tag in _DIR_RULES:
        if re.search(pat, seg):
            return tag
    return "—"
