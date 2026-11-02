"""
解析「菜单提取」脚本复制出来的文本。

它从哪来
────────────────────────────────────────────
`web/menu-sniffer.user.js` 装在你自己的浏览器里（Tampermonkey/脚本猫），
你在美团或淘宝闪购的店铺页点一下按钮，它把这一页的菜名和价格整理成文本
复制到剪贴板。然后 `python run.py 粘贴` 读剪贴板、走这个模块解析。

格式长这样（Tab 分隔，字段可选）：
    #店 麦当劳（望京店）
    #来源 美团
    #数量 3
    麦辣鸡腿堡	12.9	19.0
    板烧鸡腿堡	13.9
    可乐（中）	0	6.0

为什么用这种格式，而不是让脚本直接「发」给工具
────────────────────────────────────────────
  1. 脚本不联网，就不可能把你任何东西传出去——没有通道就没有泄漏面。
  2. 剪贴板里的东西你能看见，想改就改、想删就删，它是可审计的。
  3. 不需要工具去监听端口，不会多一个本地服务暴露面。

解析原则：认不出的行就丢掉，绝不去猜一个数字。
价格是钱，猜错比读不到糟糕得多。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_META_RE = re.compile(r"^#\s*(店|来源|数量|平台)\s*[:：]?\s*(.*)$")
_PRICE_CLEAN = re.compile(r"[¥￥元\s]")
_AMOUNT = re.compile(r"\d{1,5}(?:[.·]\d{1,2})?")

# 这些不可能是菜名，是界面标签或统计行
#
# 用的是**精确匹配**，不是包含匹配：这样「满分炸鸡」这种菜名不会被误杀，
# 而单独一行「满分」会。宁可漏掉一个标签，也不能把一道菜丢掉。
_NOISE_NAMES = {
    "起送", "起送价", "配送", "配送价", "打包费", "餐盒费", "包装费", "配送费",
    "月售", "已售", "售罄", "已售罄", "评分", "满分", "人均", "距离",
    "小计", "合计", "总计", "优惠", "满减", "红包", "会员", "优惠券",
    "去结算", "加入购物车", "立即购买", "到店自取", "选规格", "更多",
    "全部", "首页", "订单", "我的", "搜索",
}


@dataclass
class Dish:
    name: str
    price: float
    original: float | None = None

    @property
    def saved(self) -> float:
        if self.original is None or self.original <= self.price:
            return 0.0
        return round(self.original - self.price, 2)


@dataclass
class Menu:
    store: str = ""
    source: str = ""
    dishes: list[Dish] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(d.price for d in self.dishes), 2)

    @property
    def original_total(self) -> float:
        return round(
            sum(d.original if d.original and d.original > d.price else d.price
                for d in self.dishes),
            2,
        )


def _amount(raw: str) -> float | None:
    s = _PRICE_CLEAN.sub("", str(raw or "")).replace("·", ".")
    m = _AMOUNT.search(s)
    if not m:
        return None
    try:
        v = float(m.group(0).replace("·", "."))
    except ValueError:
        return None
    if v < 0 or v > 99999:
        return None
    return v


def parse_menu_text(text: str) -> Menu:
    """把剪贴板文本解析成菜单。认不出的行记在 dropped 里，供排查。"""
    menu = Menu()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = _META_RE.match(line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key == "店":
                menu.store = val
            elif key in ("来源", "平台"):
                menu.source = val
            continue

        # 允许 Tab / 竖线 / 多个空格 / 全角空格 分隔
        parts = [p.strip() for p in re.split(r"[\t|｜]+", line) if p.strip()]
        if len(parts) == 1:
            # 只有一段：可能是「菜名 12.9」用空格隔开的写法，从右往左找数字
            seg = parts[0]
            m2 = re.match(r"^(.*?)\s+[¥￥]?\s*(\d{1,5}(?:[.·]\d{1,2})?)\s*元?$", seg)
            if not m2:
                menu.dropped.append(raw_line)
                continue
            parts = [m2.group(1).strip(), m2.group(2)]

        name = parts[0]
        if not name or name in _NOISE_NAMES:
            menu.dropped.append(raw_line)
            continue
        if len(name) > 60:
            menu.dropped.append(raw_line)
            continue

        price = _amount(parts[1]) if len(parts) > 1 else None
        if price is None:
            menu.dropped.append(raw_line)
            continue

        original = _amount(parts[2]) if len(parts) > 2 else None
        if original is not None and original <= price:
            original = None

        menu.dishes.append(Dish(name=name, price=price, original=original))

    return menu


def render_menu(menu: Menu, top: int = 40) -> str:
    """把菜单排成给人看的文本。"""
    if not menu.dishes:
        out = ["没从这段文本里认出菜品。"]
        if menu.dropped:
            out.append("")
            out.append("  下面这些行没认出来（你可以检查一下格式）：")
            for line in menu.dropped[:5]:
                out.append(f"    {line[:60]}")
        out.append("")
        out.append("  正确的格式是每行「菜名<Tab>价格」，例如：")
        out.append("    麦辣鸡腿堡\t12.9")
        return "\n".join(out)

    head = menu.store or "（没读到店名）"
    if menu.source:
        head += f" · {menu.source}"
    out = [head, ""]

    for i, d in enumerate(menu.dishes[:top], 1):
        price = f"¥{d.price:.2f}"
        if d.original:
            price += f"  (原价 ¥{d.original:.2f}，省 ¥{d.saved:.2f})"
        out.append(f"  {i:>2}. {d.name}")
        out.append(f"      {price}")

    if len(menu.dishes) > top:
        out.append(f"  …… 还有 {len(menu.dishes) - top} 项没显示")

    out.append("")
    out.append(f"  共 {len(menu.dishes)} 项，合计 ¥{menu.total:.2f}")
    if menu.original_total > menu.total:
        out.append(
            f"  按原价是 ¥{menu.original_total:.2f}，"
            f"已经在标价上省了 ¥{menu.original_total - menu.total:.2f}"
        )
    return "\n".join(out)


def to_offer_spec(menu: Menu, platform: str = "") -> str:
    """转成「外卖比价」能直接用的一行：平台|菜品小计。

    这样粘完菜单可以直接接着算券和配送费，不用再手敲金额。
    """
    name = platform or menu.source or "未知平台"
    return f"{name}|{menu.total:.2f}"


def payload_from_menu(menu: Menu, notes=None) -> dict:
    """给界面/接口用的统一数据结构。

    本地服务和浏览器桥都调这个，保证「粘贴」和「一键抓」两条路
    返回的东西长得一模一样——界面上就不用写两套渲染逻辑。
    """
    return {
        "ok": True,
        "store": menu.store,
        "source": menu.source,
        "dishes": [
            {
                "name": d.name,
                "price": d.price,
                "original": d.original,
                "saved": d.saved,
            }
            for d in menu.dishes
        ],
        "total": menu.total,
        "original_total": menu.original_total,
        "text": render_menu(menu),
        "offer_spec": to_offer_spec(menu),
        "notes": list(notes or []),
    }
