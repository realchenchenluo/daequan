"""
从浏览器页面里「认出菜名和价格」。

为什么不直接照搬油猴脚本那套 JS
────────────────────────────────────────────
脚本版把判断逻辑写在了 JavaScript 里，那段代码没法在 Python 里写单测，
只能靠人肉点页面来验。这个模块把分工拆开：

  · 浏览器那边只做一件笨事：把页面上所有文字节点连同**坐标**吐出来（序列化）
  · 判断逻辑全部放在 Python 这边，纯函数，可单测

坐标是关键。同一个价格标签附近可能有好几段文字，靠"谁离它近"就能判断
哪段是菜名——这和之前截图识别用的按坐标配对是同一个思路，
只是 DOM 给的坐标是精确的，没有 OCR 错字。

为什么不用 class 名
────────────────────────────────────────────
class 名是工程内部实现，改版就变（`price_9f3a` 这种）。而「菜名在价格左边、
同一行」是**视觉事实**，改版后只要页面还是人看的，它就基本不变。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .menu import Menu, Dish

# 严格的价格形态：整段文字就是一个价格。
# 不做"包含数字就算价格"——「月售9999+」里也有数字，那不是钱。
_PRICE = re.compile(r"^[¥￥]?\s*(\d{1,5}(?:[.·]\d{1,2})?)\s*[起元]?$")

# 这些是界面标签，不是菜名。精确匹配，「满分炸鸡」不会被误杀。
_NOISE = {
    "起送", "起送价", "配送", "配送价", "打包费", "餐盒费", "包装费", "配送费",
    "月售", "已售", "售罄", "已售罄", "评分", "满分", "人均", "距离",
    "小计", "合计", "总计", "优惠", "满减", "红包", "会员", "优惠券",
    "去结算", "加入购物车", "立即购买", "到店自取", "选规格", "更多",
    "全部", "首页", "订单", "我的", "搜索", "收藏", "分享", "评价",
    "规格", "数量", "已选", "原价", "现价", "折", "元", "起", "约",
}

# 带这些前缀的是统计/说明文字，不是菜名。
# 用前缀而不是精确匹配，因为真实页面里它们是「月售9999+」「评分4.8分」这种带数的。
_LABEL_PREFIX = re.compile(
    r"^(月售|已售|已售罄|销量|评分|人均|起送|配送|打包|餐盒|距|好评|回头客|"
    r"剩余|限购|折扣|优惠|立省|已省)"
)

# 同一行的判定：两个元素垂直中心差不超过这个比例
_SAME_ROW_RATIO = 0.85
# 往上找菜名时，最多往上这么多像素。
#
# 这个值不能大。实测踩过：配送费/打包费那几行的价格，如果允许往上找 90px，
# 会一路够到上面菜品的菜名上，于是「可乐（中）」被配给了「配送费 ¥3.5」。
# 卡片式布局里菜名和价格通常只差 6~30px，60 足够。
_ABOVE_MAX_PX = 60.0
# 菜名和价格的水平距离上限（超过就认为不是同一个条目）
_HORIZONTAL_MAX_PX = 700.0
# 往上找菜名时，横向允许的偏差。卡片式布局里菜名和价格一般是对齐的，
# 但「菜名靠左、价格靠右」的卡片也有，所以给一点余量。
_ABOVE_ALIGN_PX = 160.0


@dataclass
class DomNode:
    """页面上的一个文字节点，带坐标。坐标是相对页面左上角的像素。"""

    text: str = ""
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    strike: bool = False
    tag: str = ""

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass
class DomExtract:
    """一次抽取的结果：菜单本身，加上诊断信息。"""

    menu: Menu = field(default_factory=Menu)
    url: str = ""
    title: str = ""
    price_nodes: int = 0
    notes: list[str] = field(default_factory=list)


def amount_of(text: str) -> float | None:
    """整段文字是一个价格就返回金额，否则 None。"""
    s = (text or "").strip().replace("·", ".")
    m = _PRICE.match(s)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    if v < 0 or v > 99999:
        return None
    return v


def _looks_like_name(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 2 or len(t) > 45:
        return False
    if t in _NOISE:
        return False
    if amount_of(t) is not None:
        return False
    # 带标签前缀的统计文字。「月售9999+」在真实页面里和「¥20」在同一行，
    # 精确匹配抓不住它（它不是一个固定词），所以这里按前缀拦。
    if _LABEL_PREFIX.match(t):
        return False
    # 「满30减5」这类优惠文案也不是菜名。用「满+数字」判，而不是「满」开头，
    # 免得把「满汉全席」这种真菜名误杀。
    if re.match(r"^满\s*\d", t):
        return False
    # 纯符号 / 纯日期 / 纯数字串
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", t):
        return False
    return True


def _same_row(price: DomNode, other: DomNode) -> bool:
    base = max(price.h, other.h, 8.0)
    return abs(price.cy - other.cy) <= base * _SAME_ROW_RATIO


def _is_store_title(node: DomNode, store: str) -> bool:
    """这段文字是不是店名/店铺标题，而不是某道菜。

    实测踩过：示例页顶部的 h1「示例小馆（自检用）」和下面那行的「¥20」离得近，
    被配成了一道 20 元的菜。店名本来就不该出现在菜单里。
    """
    if node.tag.upper() in ("H1", "H2"):
        return True
    if not store:
        return False
    t = node.text.strip()
    return t == store or store in t or t in store


def _overlaps_x(a: DomNode, b: DomNode) -> bool:
    return a.x < b.right and b.x < a.right


def _name_for(price: DomNode, nodes: list[DomNode], store: str = "") -> str:
    """给一个价格找它对应的菜名。

    两种排法都要覆盖：
      · 菜名在价格左边、同一行（这是菜单列表最常见的）
      · 菜名在价格上面一行（卡片式布局）

    往上找的时候**排序方式很关键**。早先只按「离得近」和「文字长」排，
    结果两张并排的卡片里，右边那张卡的价格配到了左边那张卡的菜名——
    因为两个菜名在同一高度、长度也一样。所以现在先看横向对齐度：
    菜名和价格的横向中心越接近，越可能是同一张卡。
    """
    # 先看同一行、左边的
    left = [
        n
        for n in nodes
        if n is not price
        and _same_row(price, n)
        and n.right <= price.x + 8
        and (price.x - n.right) <= _HORIZONTAL_MAX_PX
        and _looks_like_name(n.text)
        and not _is_store_title(n, store)
    ]
    if left:
        # 同排最右边的那个就是紧挨着价格的菜名；同位置再取较长的（避免把
        # 「招牌」这种小标签当成菜名）
        left.sort(key=lambda n: (-n.right, -len(n.text)))
        best_x = left[0].right
        tied = [n for n in left if abs(n.right - best_x) <= 24]
        tied.sort(key=lambda n: -len(n.text))
        return tied[0].text

    # 再看正上方：必须是「刚好压在价格上面」的那个，不能跨行去够
    above = []
    for n in nodes:
        if n is price or not _looks_like_name(n.text):
            continue
        if _is_store_title(n, store):
            continue
        if n.bottom > price.y + 4:
            continue
        gap = price.y - n.bottom
        if gap > _ABOVE_MAX_PX:
            continue
        aligns = _overlaps_x(n, price) or abs(n.cx - price.cx) <= _ABOVE_ALIGN_PX
        if not aligns:
            continue
        # 菜名和价格之间如果夹着别的价格，说明它们不是同一个条目
        sandwiched = any(
            amount_of(o.text) is not None
            and o is not price
            and o.y < price.y
            and o.bottom > n.bottom
            for o in nodes
        )
        if sandwiched:
            continue
        above.append(n)

    if above:
        # 先看横向对齐，再看离得多近，最后看文字长度
        above.sort(
            key=lambda n: (
                0 if _overlaps_x(n, price) else 1,
                abs(n.cx - price.cx),
                price.y - n.bottom,
                -len(n.text),
            )
        )
        return above[0].text

    return ""


def _original_for(price: DomNode, nodes: list[DomNode]) -> float | None:
    """找划线价（原价）。只认被标记为删除线的那些，不猜。"""
    best = None
    for n in nodes:
        if n is price or not n.strike:
            continue
        v = amount_of(n.text)
        if v is None or v <= 0:
            continue
        if not _same_row(price, n):
            continue
        if abs(n.x - price.right) <= _HORIZONTAL_MAX_PX or abs(n.right - price.x) <= _HORIZONTAL_MAX_PX:
            if best is None or v > best:
                best = v
    return best


def store_from_title(title: str) -> str:
    """从 <title> 里猜店名。标题一般是「店名 - 美团外卖」这种。"""
    t = (title or "").strip()
    if not t:
        return ""
    head = re.split(r"[-_|｜—]", t)[0].strip()
    if 2 <= len(head) <= 40:
        return head
    return ""


def extract_from_nodes(
    nodes: list[DomNode],
    url: str = "",
    title: str = "",
    source: str = "",
) -> DomExtract:
    """从带坐标的文字节点里认出菜单。纯函数，不碰浏览器。"""
    out = DomExtract(url=url, title=title)
    out.menu.store = store_from_title(title)
    # 没显式给平台名就按域名认，省得调用方每处都自己判断一次
    out.menu.source = source or detect_source(url)

    prices = []
    for n in nodes:
        v = amount_of(n.text)
        if v is None:
            continue
        prices.append((n, v))
    out.price_nodes = len(prices)

    if not prices:
        out.notes.append("这一页没有任何「看起来是价格」的文字，可能不是店铺菜单页。")
        return out

    seen = set()
    for node, price in prices:
        # 被划掉的价是「原价」，不是卖价。
        # 早先没拦这一条，真实页面上「麦辣鸡腿堡 ¥19.0（划线）¥12.9」会被拆成
        # 两道菜：19.0 和 12.9，合计直接虚高。这是真实浏览器跑出来的 bug。
        if node.strike:
            continue
        name = _name_for(node, nodes, out.menu.store)
        if not name:
            continue
        key = (name, price)
        if key in seen:
            continue
        seen.add(key)
        original = _original_for(node, nodes)
        # 原价必须比实付高才是"原价"。读到比实付低的，那是脏数据，直接丢掉——
        # 早先这里没过滤，界面上会出现「原价 ¥12，实付 ¥15，已省 ¥0」这种鬼话。
        if original is not None and original <= price:
            original = None
        out.menu.dishes.append(Dish(name=name, price=price, original=original))

    if not out.menu.dishes:
        out.notes.append(
            f"页面上有 {len(prices)} 处价格，但没找到能跟它配对的菜名。"
            "可能是版式比较特殊，或者在购物车/结账页而不是菜单页。"
        )

    return out


def detect_source(url: str) -> str:
    u = (url or "").lower()
    if "meituan" in u:
        return "美团"
    if "ele.me" in u:
        return "淘宝闪购/饿了么"
    if "jd.com" in u:
        return "京东"
    return ""


# ──────────────────────────────────────────────────────────
# 浏览器端只需要做这一件笨事：把文字节点连同坐标吐出来
# ──────────────────────────────────────────────────────────

SNAPSHOT_JS = r"""
() => {
  const out = [];
  if (!document.body) return { title: document.title, url: location.href, nodes: out };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const t = (n.nodeValue || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 80) continue;
    const el = n.parentElement;
    if (!el) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    out.push({
      text: t,
      x: r.left + window.scrollX,
      y: r.top + window.scrollY,
      w: r.width,
      h: r.height,
      strike: (cs.textDecorationLine || '').indexOf('line-through') >= 0,
      tag: el.tagName || ''
    });
    if (out.length >= 4000) break;
  }
  return { title: document.title, url: location.href, nodes: out };
}
"""


def nodes_from_snapshot(snapshot: dict) -> list[DomNode]:
    """把浏览器返回的原始 dict 转成 DomNode 列表。脏数据直接跳过。"""
    out = []
    for raw in (snapshot or {}).get("nodes") or []:
        if not isinstance(raw, dict):
            continue
        try:
            out.append(
                DomNode(
                    text=str(raw.get("text") or ""),
                    x=float(raw.get("x") or 0),
                    y=float(raw.get("y") or 0),
                    w=float(raw.get("w") or 0),
                    h=float(raw.get("h") or 0),
                    strike=bool(raw.get("strike")),
                    tag=str(raw.get("tag") or ""),
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def extract_from_snapshot(snapshot: dict) -> DomExtract:
    """完整的落地入口：浏览器快照 → 菜单。"""
    snap = snapshot or {}
    url = str(snap.get("url") or "")
    title = str(snap.get("title") or "")
    return extract_from_nodes(
        nodes_from_snapshot(snap),
        url=url,
        title=title,
        source=detect_source(url),
    )
