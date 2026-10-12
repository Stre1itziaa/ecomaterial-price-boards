"""搜狗微信候选层(MLCC 版):周频数字锚点的候选发现器(绝不自动入锚点)。

背景(2026-10-11 复核轮结论):免费世界的"市场成交价数字"以周评转述形态
存在于券商/研究公众号(如「全产业链研究」转述卓创 2026-10-08 周评:
G75 环比 +14%、7628 成交 13.0-13.7 元/米)。本模块每日扫一次搜狗微信,
把带价格数字的公众号文章写入 pending_anchors 表,**只做候选**——
机器保证不漏报,口径与入库由人工点验(`--review` / `--mark`)。

风控纪律(对齐 ali.py):①每日只在 update 里跑一轮,查询间 sleep;
②响应含 antispider/验证特征即写 data/wx_flag.json 熔断冷却 2 天;
③免登录、无个人信息;跳转链接用搜狗公开跳转,不碰任何付费内容。

搜狗接口经验(2026-10-11 实测):
- 必须先 GET 首页拿 SUID/ABTEST cookie 再搜,否则回 6.7KB 空壳;
- query 直接拼在 URL 串上(requests params 编码形态会触发空壳);
- 公众号名在 span.all-time-y2,发布时间为 timeConvert('unix') 字面量。
"""

from . import tz
import datetime as dt
import html as htmllib
import json
import pathlib
import re
import time

import requests

from . import store

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "mlcc.db"
FLAG = ROOT / "data" / "wx_flag.json"     # {"last_captcha": date}
COOLDOWN_DAYS = 2
MAX_DAYS = 21                             # 只收最近 N 天文章(时间戳过滤)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/120 Safari/537.36", "Referer": "https://weixin.sogou.com/"}

# (搜索词,)——控制在 4 个,查询间 sleep,宁少勿拦
QUERIES = ["MLCC 涨价", "村田 MLCC 调价", "三星电机 MLCC 涨价", "MLCC 交期 缺货"]

# 品目/主体识别:标题/摘要/正文命中即记(品牌×容值段)
ITEM_PATTERNS = [
    ("村田", r"村田|murata"), ("三星电机", r"三星电机|semco"),
    ("太阳诱电", r"太阳诱电|太诱"), ("国巨", r"国巨|yageo"),
    ("TDK", r"tdk"), ("三环集团", r"三环"), ("风华高科", r"风华"),
    ("高容/AI 服务器", r"高容|ai 服务器|ai服务器|x6s|x7s"),
    ("车规", r"车规|车用"), ("消费级", r"消费级|常规料"),
]
# 数字片段:抓"数字+单位"及其前后文,供人工核验,机器不定价
NUM_PATTERN = re.compile(r"[^。;；\n]{0,42}\d[\d,.]*\s*(?:元\s*/\s*(?:吨|米|公斤|kg|㎡)|元(?:人民币)?/吨|万?元/吨|%|元/米)[^。;；\n]{0,30}")

RE_BLOCK = re.compile(r'<li id="sogou_vr[^"]*"(.*?)</li>', re.S)
RE_TITLE = re.compile(r'<h3>\s*<a[^>]*href="(/link\?url=[^"]+)"[^>]*>(.*?)</a>', re.S)
RE_INFO = re.compile(r'<p class="txt-info"[^>]*>(.*?)</p>', re.S)
RE_ACC = re.compile(r'<span class="all-time-y2">([^<]+)</span>')
RE_TS = re.compile(r"timeConvert\('(\d+)'\)")


def _flagged() -> bool:
    if not FLAG.exists():
        return False
    try:
        d = json.loads(FLAG.read_text())["last_captcha"]
        return (tz.today() - dt.date.fromisoformat(d)).days < COOLDOWN_DAYS
    except Exception:
        return False


def _set_flag():
    FLAG.parent.mkdir(parents=True, exist_ok=True)
    FLAG.write_text(json.dumps({"last_captcha": tz.today().isoformat()}))


def _clean(seg: str) -> str:
    seg = re.sub(r"<em>|</em>|<!--red_beg-->|<!--red_end-->", "", seg)
    return htmllib.unescape(re.sub(r"<[^>]+>", "", seg)).strip()


def _resolve_link(session, link: str) -> str | None:
    """搜狗 /link?url=... → 微信原文 URL(响应页 JS url += '...' 拼接)。"""
    try:
        r = session.get("https://weixin.sogou.com" + link, timeout=20)
        parts = re.findall(r"url \+= '([^']*)'", r.text)
        if parts:
            return "".join(parts).replace("@", "")
    except Exception:
        pass
    return None


def _fetch_article(session, wx_url: str):
    """抓原文正文,返回 (纯文本, 公众号名, 发布日期)。失败返 (None, None, None)。"""
    try:
        r = requests.get(wx_url, headers={"User-Agent": UA["User-Agent"]}, timeout=25)
        txt = r.text
        if "环境异常" in txt or "验证" in txt[:2000]:
            _set_flag()
            return None, None, None
        body = re.sub(r"<script.*?</script>", "", txt, flags=re.S)
        body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body)
        acc = re.search(r'id="js_name"[^>]*>\s*([^<]+?)\s*<', txt)
        ts = (re.search(r"var createTime = '(\d+)'", txt)
              or re.search(r'publish_time":"([\d\-]+)', txt)
              or re.search(r"var oriCreateTime = '(\d+)'", txt))
        pub = None
        if ts:
            v = ts.group(1)
            pub = v[:10] if "-" in v else dt.datetime.fromtimestamp(
                int(v)).date().isoformat()
        return body, acc.group(1).strip() if acc else None, pub
    except Exception:
        return None, None, None


def _hit_items(text: str) -> list:
    low = text.lower()
    return [name for name, pat in ITEM_PATTERNS if re.search(pat, low)]


def scan(max_queries: int = len(QUERIES), verbose: bool = True) -> list[dict]:
    """跑一轮扫描,返回本轮候选(不入库;入库走 scan_and_store)。"""
    if _flagged():
        if verbose:
            print("[wx] 熔断冷却中(上次拦截 "
                  f"{json.loads(FLAG.read_text())['last_captcha']}),跳过")
        return []
    s = requests.Session()
    s.headers.update(UA)
    try:
        s.get("https://weixin.sogou.com/", timeout=20)   # 预热拿 SUID/ABTEST
    except Exception:
        pass
    cutoff = tz.today() - dt.timedelta(days=MAX_DAYS)
    out, seen = [], set()
    for q in QUERIES[:max_queries]:
        from urllib.parse import quote
        try:
            r = s.get("https://weixin.sogou.com/weixin?type=2&query="
                      + quote(q), timeout=25)
        except Exception as e:
            if verbose:
                print(f"[wx] {q}: {type(e).__name__}")
            continue
        raw = r.content.decode("utf-8", "replace")
        if "antispider" in raw.lower() or "验证码" in raw:
            _set_flag()
            if verbose:
                print("[wx] 命中反爬→熔断 2 天(详见 wxscan.py 注释)")
            break
        n_new = 0
        for m in RE_BLOCK.finditer(raw):
            seg = m.group(1)
            tm = RE_TITLE.search(seg)
            if not tm:
                continue
            link, title = tm.group(1), _clean(tm.group(2))
            info = _clean(RE_INFO.search(seg).group(1)) if RE_INFO.search(seg) else ""
            acc = RE_ACC.search(seg)
            tsm = RE_TS.search(seg)
            pub = (dt.datetime.fromtimestamp(int(tsm.group(1))).date()
                   if tsm else None)
            if pub and pub < cutoff:
                continue
            key = title
            if key in seen:
                continue
            seen.add(key)
            out.append({"link": link, "title": title, "excerpt": info,
                        "account": acc.group(1).strip() if acc else None,
                        "pub_date": pub.isoformat() if pub else None,
                        "query": q})
            n_new += 1
        if verbose:
            print(f"[wx] {q}: {n_new} 条候选")
        time.sleep(8)   # 查询间隔,风控友好
    return out


def scan_and_store(con, verbose: bool = True) -> int:
    """扫描+解原文+抽数字片段+入库(pending_anchors,状态=待核验)。"""
    cands = scan(verbose=verbose)
    now = tz.now().isoformat(timespec="seconds")
    n_new = 0
    for c in cands:
        # resolve 用带 cookie 的会话更稳:重开一个并预热
        ses = requests.Session()
        ses.headers.update(UA)
        try:
            ses.get("https://weixin.sogou.com/", timeout=20)
        except Exception:
            pass
        wx = _resolve_link(ses, c["link"])
        body = acc2 = pub2 = None
        if wx:
            body, acc2, pub2 = _fetch_article(ses, wx)
        text = body or f'{c["title"]} {c["excerpt"]}'
        nums = [m.group(0).strip() for m in NUM_PATTERN.finditer(text)]
        # 去重+只留带数字的候选:没数字的周评转述对锚点层无价值
        if not nums:
            continue
        items = _hit_items(c["title"] + " " + c["excerpt"] + " " + (body or "")[:4000])
        cur = con.execute(
            "INSERT OR IGNORE INTO pending_anchors"
            "(url,found_at,pub_date,account,title,excerpt,nums,items,status,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (wx or f"sogou:{c['title']}", now, c["pub_date"],
             acc2 or c["account"], c["title"],
             c["excerpt"][:300], json.dumps(nums[:8], ensure_ascii=False),
             json.dumps(items, ensure_ascii=False), "待核验", now))
        n_new += cur.rowcount
    con.commit()
    return n_new


def review(con):
    rows = con.execute("SELECT * FROM pending_anchors "
                       "ORDER BY found_at DESC, pub_date DESC").fetchall()
    if not rows:
        print("候选队列为空")
        return
    print("── 核验 SOP ──")
    print("  1.原文可打开 2.数字与原文逐字复核 3.口径可判定(判不清→只入涨幅或否决)")
    print("  绝对价需≥2家独立转引;涨幅类单源可收。等级上限=卓创/百川编辑质量。")
    print("────────────")
    for r in rows:
        print(f"[{r['status']}] {r['pub_date'] or '?'} @{r['account']} "
              f"| {r['title'][:56]}")
        for n in json.loads(r["nums"] or "[]")[:5]:
            print(f"    · {n}")
        print(f"    {r['url'][:110]}")


def mark(con, url: str, status: str):
    assert status in ("待核验", "已采纳", "已否决"), "status 限:待核验/已采纳/已否决"
    con.execute("UPDATE pending_anchors SET status=? WHERE url=?", (status, url))
    con.commit()
    print(f"已标记 {status}: {url[:80]}")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", action="store_true", help="列出候选队列")
    ap.add_argument("--mark", nargs=2, metavar=("URL", "状态"),
                    help="标记候选状态(待核验/已采纳/已否决)")
    ap.add_argument("--reset-flag", action="store_true",
                    help="手动清除熔断标记(仅在确认风控已放松时使用,如次日白天)")
    ap.add_argument("--max-queries", type=int, default=len(QUERIES))
    args = ap.parse_args()
    con = store.connect(DB)
    if args.review:
        review(con)
    elif args.reset_flag:
        if FLAG.exists():
            FLAG.unlink()
            print("熔断标记已清除(下次扫描正常运行;若再次命中反爬会立即重新熔断)")
        else:
            print("无熔断标记")
    elif args.mark:
        mark(con, args.mark[0], args.mark[1])
    else:
        n = scan_and_store(con)
        total = con.execute("SELECT COUNT(*) FROM pending_anchors "
                            "WHERE status='待核验'").fetchone()[0]
        print(f"[wx] 候选新增 {n} / 待核验 {total}")
    con.close()


if __name__ == "__main__":
    main()
