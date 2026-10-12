"""数据源时区(中国 GMT+8)。巡检/时效判定统一用源时区,不依赖运行机器本地时区
(海外机器本地时区跑会导致 age 系统性偏差,2026-10-12 review 引入)。"""
import datetime as dt

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Shanghai")
except ImportError:
    _TZ = None


def now():
    """上海墙钟(naive datetime),与既有 naive 字段/算术完全兼容。"""
    if _TZ:
        return dt.datetime.now(_TZ).replace(tzinfo=None)
    return dt.datetime.now()


def today():
    return now().date()
