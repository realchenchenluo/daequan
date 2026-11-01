"""
解析外卖平台的「商家列表页」文字。

为什么单独一个模块
────────────────────────────────────────────
商家列表不是商品页：它没有「券后价」「到手价」这种字样，
而是一堆短标签拼起来的：

    高济百康药房（蒋台路分店）
    5.0分
    月售9999+
    美团专送
    起送 ¥20
    配送 约¥3.5
    34分钟
    3.5km
    “不卖临期药”

上面这段是 2026-10 从美团外卖 H5 首页真实读出来的，不是编的。
商品页解析器（product.py）吃不下这种结构，所以这里单独处理。

解析策略：先认出「详情行」，剩下的就是店名
────────────────────────────────────────────
详情行的特征是**格式高度固定**（评分、月售、起送、配送、分钟、km）。
把这些格式全部认出来，逐个消费，遇到不是详情行的，就当店名。
这样不依赖任何 class 名或页面结构，平台改版只要标签文字不变就还能用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 详情行 —— 命中任意一条就认为这一行属于「某个商家」，不是店名
_RATING = re.compile(r"^(\d(?:\.\d)?)\s*分$")
_SALES = re.compile(r"^(?:月售|已售|月销)\s*([0-9]+\+?|[0-9]+(?:\.[0-9])?万\+?)$")
_AVG = re.compile(r"^(?:人均|客单)\s*[¥￥]?\s*(\d{1,4}(?:\.\d{1,2})?)$")
_MIN_ORDER = re.compile(r"^起送\s*[¥￥]?\s*(\d{1,4}(?:\.\d{1,2})?)$")
_MIN_ORDER_REV = re.compile(r"^[¥￥]?\s*(\d{1,4}(?:\.\d{1,2})?)\s*起送$")
_DELIVERY = re.compile(
    r"^配送(?:费)?\s*(?:约)?\s*[¥￥]?\s*(\d{1,3}(?:\.\d{1,2})?)$"
)
_ETA = re.compile(r"^约?\s*(\d{1,3})\s*分钟$")
_DIST = re.compile(r"^(\d{1,3}(?:\.\d{1,2})?)\s*(?:km|KM|千米|公里)$")
_QUOTE = re.compile(r'^[“"「](.{1,30})[”"」]$')
_RANK = re.compile(r"^.*榜\s*第\s*\d+\s*名$")
# 配送方式标签（这类是纯名词，没有数字）
_DELIVERY_MODES = (
    "美团专送",
    "美团快送",
    "商家配送",
    "蜂鸟专送",
    "蜂鸟快送",
    "准时达",
    "专送",
    "快送",
    "自配送",
    "品牌专送",
)
# 这些不是店名，是界面导航/提示
_NOT_NAME = (
    "搜索结果",
    "正在加载",
    "加载中",
    "首页",
    "订单",
    "我的",
    "搜索",
    "去开启",
    "综合排序",
    "销量最高",
    "距离最近",
    "筛选",
    "全部",
    "附近商家",
    "没有更多",
    "到底了",
)

_NAME_MIN = 2
_NAME_MAX = 60


@dataclass
class Store:
    """列表页里的一家店。字段都是「能读到就填，读不到就是 None」。"""

    name: str = ""
    rating: float | None = None
    monthly_sales: str = ""
    avg_price: float | None = None
    min_order: float | None = None
    delivery_fee: float | None = None
    eta_min: int | None = None
    distance_km: float | None = None
    delivery_mode: str = ""
    quote: str = ""
    rank: str = ""

    def key(self) -> str:
        """去重用的键：店名 + 起送价（同名连锁店的区分很弱，但够用）。"""
        return f"{self.name}|{self.min_order}"


def _is_detail(line: str) -> bool:
    for pat in (
        _RATING,
        _SALES,
        _AVG,
        _MIN_ORDER,
        _MIN_ORDER_REV,
        _DELIVERY,
        _ETA,
        _DIST,
        _QUOTE,
        _RANK,
    ):
        if pat.match(line):
            return True
    return line in _DELIVERY_MODES


def _absorb(store: Store, line: str) -> None:
    """把一条详情行塞进 Store。认不出就忽略——不猜。"""
    m = _RATING.match(line)
    if m:
        store.rating = float(m.group(1))
        return
    m = _SALES.match(line)
    if m:
        store.monthly_sales = m.group(1)
        return
    m = _AVG.match(line)
    if m:
        store.avg_price = float(m.group(1))
        return
    m = _MIN_ORDER.match(line) or _MIN_ORDER_REV.match(line)
    if m:
        store.min_order = float(m.group(1))
        return
    m = _DELIVERY.match(line)
    if m:
        store.delivery_fee = float(m.group(1))
        return
    m = _ETA.match(line)
    if m:
        store.eta_min = int(m.group(1))
        return
    m = _DIST.match(line)
    if m:
        store.distance_km = float(m.group(1))
        return
    m = _QUOTE.match(line)
    if m:
        store.quote = m.group(1)
        return
    if _RANK.match(line):
        store.rank = line
        return
    if line in _DELIVERY_MODES:
        store.delivery_mode = line


def _looks_like_name(line: str) -> bool:
    s = line.strip()
    if not (_NAME_MIN <= len(s) <= _NAME_MAX):
        return False
    if s in _NOT_NAME:
        return False
    # 纯数字/纯符号不可能是店名
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", s):
        return False
    return True


def parse_store_list(text: str) -> list[Store]:
    """从商家列表页的文字里拆出一家家店。

    返回的列表按页面出现顺序排列。一个店至少要有评分/月售/起送/配送
    里的任意一项，否则不收录——避免把纯文字广告当成店。
    """
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if l]

    stores: list[Store] = []
    current: Store | None = None
    current_detail_count = 0

    def flush() -> None:
        nonlocal current, current_detail_count
        if current is not None and current_detail_count > 0:
            stores.append(current)
        current = None
        current_detail_count = 0

    for line in lines:
        if _is_detail(line):
            if current is not None:
                _absorb(current, line)
                current_detail_count += 1
            # current 为 None 说明这是页面顶部的杂项（比如排序标签），丢掉
            continue

        if not _looks_like_name(line):
            continue

        # 走到这里是一个「非详情行」，按说应该是店名。
        # 但如果上一个店还没吃到任何详情，说明上一行才是真店名，
        # 这一行可能只是副标题 —— 用更强的名字替换掉那个占位的。
        flush()
        current = Store(name=line)

    flush()
    return stores


def render_stores(stores: list[Store], keyword: str = "") -> str:
    """把商家列表排成给人看的文本。"""
    if not stores:
        head = f'没在这个页面上读出商家。' if not keyword else f'没找到「{keyword}」的商家。'
        return (
            head
            + "\n"
            "  可能原因：页面还没加载完、这是个商品页而不是列表页，或者平台改版了。"
        )

    out = []
    if keyword:
        out.append(f'「{keyword}」共读到 {len(stores)} 家店：')
    else:
        out.append(f"共读到 {len(stores)} 家店：")
    out.append("")

    for i, s in enumerate(stores, 1):
        bits = []
        if s.rating is not None:
            bits.append(f"{s.rating}分")
        if s.monthly_sales:
            bits.append(f"月售{s.monthly_sales}")
        if s.eta_min is not None:
            bits.append(f"{s.eta_min}分钟")
        if s.distance_km is not None:
            bits.append(f"{s.distance_km}km")

        money = []
        if s.min_order is not None:
            money.append(f"起送¥{s.min_order:g}")
        if s.delivery_fee is not None:
            money.append(f"配送¥{s.delivery_fee:g}")
        if s.avg_price is not None:
            money.append(f"人均¥{s.avg_price:g}")

        out.append(f"  {i}. {s.name}")
        if bits:
            out.append(f"     {' · '.join(bits)}")
        if money:
            out.append(f"     {' · '.join(money)}")
        extra = []
        if s.delivery_mode:
            extra.append(s.delivery_mode)
        if s.rank:
            extra.append(s.rank)
        if s.quote:
            extra.append(f"“{s.quote}”")
        if extra:
            out.append(f"     {' · '.join(extra)}")

    cheapest = [s for s in stores if s.delivery_fee is not None]
    if len(cheapest) >= 2:
        best = min(cheapest, key=lambda s: (s.delivery_fee or 0, s.min_order or 0))
        out.append("")
        out.append(
            f"  配送最便宜：{best.name}（配送¥{best.delivery_fee:g}，"
            f"起送¥{best.min_order:g}）"
            if best.min_order is not None
            else f"  配送最便宜：{best.name}（配送¥{best.delivery_fee:g}）"
        )

    return "\n".join(out)
