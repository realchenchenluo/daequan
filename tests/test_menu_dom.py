#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「从页面坐标里认菜名和价格」的自检。跑法：python tests/test_menu_dom.py

这里全部用**人造坐标**，不需要浏览器、不联网，所以能跑得很快、很稳。
每个用例都对应一种真实见过的排版：

  · 菜名在左、价格在右、同一行（列表式）
  · 菜名在上、价格在下（卡片式）
  · 划线原价在价格旁边
  · 界面标签混在菜名位置（"起送""月售"）
  · 一屏里两列价格互不串条目

测的核心是**配对**：价格配错菜名，比认不出更糟。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.menu_dom import (  # noqa: E402
    DomNode,
    _looks_like_name,
    amount_of,
    detect_source,
    extract_from_nodes,
    extract_from_snapshot,
    nodes_from_snapshot,
    store_from_title,
)

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


def node(text, x, y, w=None, h=18, strike=False, tag="SPAN"):
    """按「左上角坐标 + 宽度」造一个文字节点。宽度默认按字数估。"""
    if w is None:
        w = max(12.0, len(text) * 14.0)
    return DomNode(text=text, x=float(x), y=float(y), w=float(w), h=float(h),
                   strike=strike, tag=tag)


# ── 金额识别 ─────────────────────────────────────────

@case("金额：整段是价格才算")
def _():
    assert amount_of("¥12.9") == 12.9
    assert amount_of("12.9") == 12.9
    assert amount_of("￥12.90元") == 12.9
    assert amount_of("12·9") == 12.9
    assert amount_of("¥0") == 0.0
    return "¥/￥/元/中间点 都认"


@case("金额：不是整段价格的，一律不算（关键防线）")
def _():
    for bad in ("月售9999+", "起送 ¥20", "配送 约¥3.5", "已售1000+",
                "满30减5", "1.5km", "34分钟", "5.0分", "¥12.9起送"):
        assert amount_of(bad) is None, f"「{bad}」被误判成价格了"
    return "9 种非价格文本全部拒绝"


# ── 标题 → 店名 ──────────────────────────────────────

@case("店名：从标题里按分隔符切出来")
def _():
    assert store_from_title("麦当劳（望京店） - 美团外卖") == "麦当劳（望京店）"
    assert store_from_title("肯德基宅急送_淘宝闪购") == "肯德基宅急送"
    assert store_from_title("") == ""
    return "三种分隔符都认"


@case("店名：标题为空时不瞎猜")
def _():
    assert store_from_title("") == ""
    assert store_from_title("   ") == ""
    return "空标题返回空"


@case("来源：按域名判断平台")
def _():
    assert detect_source("https://h5.waimai.meituan.com/x") == "美团"
    assert detect_source("https://h5.ele.me/x") == "淘宝闪购/饿了么"
    assert detect_source("https://x.jd.com/y") == "京东"
    assert detect_source("https://example.com") == ""
    return "四种情况"


# ── 列表式排版：菜名在左、价格在右、同一行 ────────────

LISTISH = [
    node("麦辣鸡腿堡", 20, 100, w=110),
    node("¥12.9", 300, 102, w=52),
    node("板烧鸡腿堡", 20, 140, w=110),
    node("¥13.9", 300, 142, w=52),
    node("可乐（中）", 20, 180, w=90),
    node("¥0", 300, 182, w=30),
]


@case("列表式：三行各自配对，不串")
def _():
    ex = extract_from_nodes(LISTISH, url="https://h5.waimai.meituan.com/x",
                            title="麦当劳（望京店） - 美团外卖")
    got = [(d.name, d.price) for d in ex.menu.dishes]
    assert got == [("麦辣鸡腿堡", 12.9), ("板烧鸡腿堡", 13.9), ("可乐（中）", 0.0)], got
    assert ex.menu.store == "麦当劳（望京店）"
    assert ex.menu.source == "美团"
    return "3 行全对，店名和来源也对"


@case("列表式：0 元条目要保留")
def _():
    ex = extract_from_nodes(LISTISH)
    assert any(d.price == 0.0 for d in ex.menu.dishes)
    return "0 元换购没被丢掉"


@case("列表式：合计只算价格")
def _():
    ex = extract_from_nodes(LISTISH)
    assert ex.menu.total == 26.8, ex.menu.total
    return "合计 ¥26.80"


# ── 卡片式排版：菜名在上、价格在下 ────────────────────

CARDS = [
    node("香草拿铁", 40, 100, w=96),
    node("¥19.9", 40, 126, w=58),
    node("玫瑰青提", 200, 100, w=96),
    node("¥22.0", 200, 126, w=58),
]


@case("卡片式：价格在下，往上找菜名")
def _():
    ex = extract_from_nodes(CARDS)
    got = sorted((d.name, d.price) for d in ex.menu.dishes)
    assert got == [("玫瑰青提", 22.0), ("香草拿铁", 19.9)], got
    return "两张卡各自配对"


# ── 划线原价 ────────────────────────────────────────

@case("划线原价：只认删除线标记，不猜")
def _():
    nodes = [
        node("鸡腿堡", 20, 100, w=70),
        node("¥12.9", 300, 102, w=52),
        node("¥19.0", 360, 102, w=52, strike=True),
    ]
    ex = extract_from_nodes(nodes)
    d = ex.menu.dishes[0]
    assert d.original == 19.0, d.original
    assert d.saved == 6.1, d.saved
    return "原价 ¥19.0，省 ¥6.10"


@case("划线原价：没有删除线标记就不当原价")
def _():
    nodes = [
        node("鸡腿堡", 20, 100, w=70),
        node("¥12.9", 300, 102, w=52),
        node("¥19.0", 360, 102, w=52, strike=False),
    ]
    ex = extract_from_nodes(nodes)
    assert ex.menu.dishes[0].original is None
    return "同样位置，没有删除线就不算原价"


@case("划线原价：比实付还低就丢掉")
def _():
    nodes = [
        node("鸡腿堡", 20, 100, w=70),
        node("¥15.0", 300, 102, w=52),
        node("¥12.0", 360, 102, w=52, strike=True),
    ]
    ex = extract_from_nodes(nodes)
    assert ex.menu.dishes[0].original is None
    return "原价 12 < 实付 15，判为脏数据"


# ── 干扰项 ──────────────────────────────────────────

@case("界面标签不能当菜名")
def _():
    nodes = [
        node("起送", 20, 100, w=40),
        node("¥20", 300, 102, w=40),
        node("月售", 20, 140, w=40),
        node("¥9999", 300, 142, w=58),
    ]
    ex = extract_from_nodes(nodes)
    names = [d.name for d in ex.menu.dishes]
    assert names == [], names
    return "「起送/月售 + 价格」不会被当成菜品"


@case("纯数字、纯符号不可能是菜名")
def _():
    nodes = [
        node("12345", 20, 100, w=60),
        node("¥9.9", 300, 102, w=46),
    ]
    ex = extract_from_nodes(nodes)
    assert ex.menu.dishes == [], [d.name for d in ex.menu.dishes]
    return "数字串被拒"


@case("菜单页里混着别的价格也不会配错")
def _():
    nodes = LISTISH + [
        node("配送费", 20, 260, w=56),
        node("¥3.5", 300, 262, w=46),
        node("打包费", 20, 300, w=56),
        node("¥1", 300, 302, w=20),
    ]
    ex = extract_from_nodes(nodes)
    got = [(d.name, d.price) for d in ex.menu.dishes]
    assert len(got) == 3, got
    assert all("费" not in n for n, _ in got), got
    return "配送费/打包费那两行被正确排除"


@case("同一行多个候选菜名：取紧挨价格的那个")
def _():
    nodes = [
        node("招牌", 20, 100, w=40),
        node("麦辣鸡腿堡", 80, 100, w=110),
        node("¥12.9", 300, 102, w=52),
    ]
    ex = extract_from_nodes(nodes)
    assert ex.menu.dishes[0].name == "麦辣鸡腿堡", ex.menu.dishes[0].name
    return "跳过左侧的「招牌」小标签"


@case("价格左边什么都没有：宁可不收，也不配错")
def _():
    nodes = [node("¥12.9", 300, 102, w=52)]
    ex = extract_from_nodes(nodes)
    assert ex.menu.dishes == []
    assert any("没找到能跟它配对" in n for n in ex.notes), ex.notes
    return "孤零零的价格被丢弃并给出提示"


@case("整页没有价格：明确说这页可能不是菜单页")
def _():
    ex = extract_from_nodes([node("首页", 10, 10), node("我的", 10, 40)])
    assert ex.menu.dishes == []
    assert any("不是店铺菜单页" in n for n in ex.notes), ex.notes
    return "提示语可操作"


@case("空页面不炸")
def _():
    ex = extract_from_nodes([])
    assert ex.menu.dishes == []
    assert ex.price_nodes == 0
    return "空输入返回空结果"


# ── 浏览器快照的解析 ────────────────────────────────

@case("快照：脏数据要跳过，不能整批崩")
def _():
    snap = {
        "url": "https://h5.waimai.meituan.com/x",
        "title": "麦当劳（望京店） - 美团外卖",
        "nodes": [
            {"text": "鸡腿堡", "x": 20, "y": 100, "w": 70, "h": 18},
            {"text": "¥12.9", "x": 300, "y": 102, "w": 52, "h": 18},
            {"text": "坏节点", "x": "不是数字", "y": None},
            "字符串不是对象",
            None,
        ],
    }
    ex = extract_from_snapshot(snap)
    assert len(ex.menu.dishes) == 1, ex.menu.dishes
    assert ex.menu.dishes[0].price == 12.9
    return "坏节点被跳过，好数据照常解析"


@case("快照：nodes 缺失或不是列表时不炸")
def _():
    assert extract_from_snapshot({}).menu.dishes == []
    assert extract_from_snapshot({"nodes": None}).menu.dishes == []
    assert nodes_from_snapshot(None) == []
    return "三种空输入都安全"


@case("快照：完整走通，来源和店名都填上")
def _():
    snap = {
        "url": "https://h5.ele.me/x",
        "title": "沪上阿姨（望京店） - 淘宝闪购",
        "nodes": [
            {"text": "玫瑰青提", "x": 20, "y": 100, "w": 70, "h": 18},
            {"text": "¥15.9", "x": 300, "y": 102, "w": 52, "h": 18},
        ],
    }
    ex = extract_from_snapshot(snap)
    assert ex.menu.store == "沪上阿姨（望京店）", ex.menu.store
    assert ex.menu.source == "淘宝闪购/饿了么", ex.menu.source
    assert ex.menu.dishes[0].name == "玫瑰青提"
    return "店名/平台/菜品 三样都对"


@case("回归：划线原价不能自己变成一道菜")
def _():
    # 真实浏览器跑出来的 bug：页面上「麦辣鸡腿堡 ¥19.0(划线) ¥12.9」被拆成两道菜，
    # 合计直接虚高。划线价是原价，不是卖价。
    nodes = [
        node("麦辣鸡腿堡", 20, 100, w=110),
        node("¥19.0", 300, 102, w=52, strike=True),
        node("¥12.9", 360, 102, w=52),
    ]
    ex = extract_from_nodes(nodes)
    got = [(d.name, d.price, d.original) for d in ex.menu.dishes]
    assert got == [("麦辣鸡腿堡", 12.9, 19.0)], got
    assert ex.menu.total == 12.9, ex.menu.total
    return "只有一道菜，原价 19.0 挂上去，合计 12.9"


@case("回归：月售9999+ 不能当菜名")
def _():
    # 真实页面顶部是「评分 4.8分 / 月售9999+ / 起送 / ¥20」排在一行，
    # 那个 ¥20 早先被配给了「月售9999+」，凭空多出一道 20 元的菜。
    nodes = [
        node("评分 4.8分", 20, 60, w=90),
        node("月售9999+", 130, 60, w=90),
        node("起送", 240, 60, w=40),
        node("¥20", 300, 60, w=40),
    ]
    ex = extract_from_nodes(nodes)
    assert ex.menu.dishes == [], [d.name for d in ex.menu.dishes]
    return "起送 ¥20 这一整行被正确排除"


@case("带标签前缀的文字都不当菜名")
def _():
    for bad in ("月售999+", "已售1000+", "评分4.8分", "人均¥39", "起送¥20",
                "配送约¥3.5", "打包费$1", "限购2份", "立省14元"):
        assert not _looks_like_name(bad), f"「{bad}」被当成菜名了"
    for good in ("麦辣鸡腿堡", "香辣鸡翅（2块）", "可乐（中）"):
        assert _looks_like_name(good), f"「{good}」被误杀了"
    return "9 个标签全拦，3 个真菜名都留着"


@case("回归：店名标题不能变成一道菜")
def _():
    # 真实浏览器跑出来的 bug：h1 店名和下面那行的「¥20」离得近，
    # 被配成了「示例小馆（自检用） ¥20.0」这样一道凭空出现的菜。
    nodes = [
        DomNode(text="示例小馆（自检用）", x=16, y=40, w=220, h=28, tag="H1"),
        node("起送", 240, 80, w=40),
        node("¥20", 300, 80, w=40),
        node("麦辣鸡腿堡", 20, 120, w=110),
        node("¥12.9", 300, 122, w=52),
    ]
    ex = extract_from_nodes(nodes, title="示例小馆 - 自检用菜单页")
    got = [(d.name, d.price) for d in ex.menu.dishes]
    assert got == [("麦辣鸡腿堡", 12.9)], got
    assert ex.menu.store == "示例小馆", ex.menu.store
    return "只有鸡腿堡，店名留在 store 里"


@case("「满30减5」这种优惠文案不能当菜名")
def _():
    nodes = [
        node("满30减5", 20, 60, w=80),
        node("鸡腿堡", 20, 120, w=70),
        node("¥12.9", 300, 122, w=52),
    ]
    assert not _looks_like_name("满30减5")
    ex = extract_from_nodes(nodes)
    assert [d.name for d in ex.menu.dishes] == ["鸡腿堡"], ex.menu.dishes
    # 但「满汉全席」这种真菜名不能被误杀
    assert _looks_like_name("满汉全席")
    return "优惠文案拦住，真菜名保留"


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            detail = fn()
            print(f"  ✓ {name}")
            if detail:
                print(f"      {detail}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {name}")
            print(f"      {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}（异常）")
            print(f"      {type(e).__name__}: {e}")

    print()
    print(f"  {len(CASES) - failed}/{len(CASES)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
