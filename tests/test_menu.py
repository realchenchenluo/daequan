#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
菜单粘贴解析的自检。跑法：python tests/test_menu.py

这份东西是「浏览器脚本复制 → 工具读剪贴板」那条路的中间环节。
它出错的形式很讨厌：不报错，但金额错了。所以下面每一条都在盯钱。
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.clipboard import ClipboardError, read_source  # noqa: E402
from coupon_hunter.menu import (  # noqa: E402
    parse_menu_text,
    render_menu,
    to_offer_spec,
)

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


REAL = (
    "#店 麦当劳（望京店）\n"
    "#来源 美团\n"
    "#数量 3\n"
    "麦辣鸡腿堡\t12.9\t19.0\n"
    "板烧鸡腿堡\t13.9\n"
    "可乐（中）\t0\t6.0\n"
)


@case("标准格式：三项都对上")
def _():
    m = parse_menu_text(REAL)
    assert m.store == "麦当劳（望京店）", m.store
    assert m.source == "美团", m.source
    assert len(m.dishes) == 3, len(m.dishes)
    assert m.dishes[0].name == "麦辣鸡腿堡"
    assert m.dishes[0].price == 12.9
    assert m.dishes[0].original == 19.0
    return "店名/来源/3 项都认出来了"


@case("合计只算实付价，不把原价加进去")
def _():
    m = parse_menu_text(REAL)
    assert m.total == 26.8, m.total
    assert m.original_total == 38.9, m.original_total
    return f"实付 ¥{m.total} / 原价 ¥{m.original_total}"


@case("0 元的可乐要保留（赠品/换购），不能当成读错")
def _():
    m = parse_menu_text(REAL)
    cola = [d for d in m.dishes if "可乐" in d.name][0]
    assert cola.price == 0.0, cola.price
    return "0 元项保留，合计不受影响"


@case("原价比实付还低 → 当脏数据丢掉，不算省钱")
def _():
    m = parse_menu_text("某汉堡\t15.0\t12.0")
    assert m.dishes[0].original is None, m.dishes[0].original
    assert m.dishes[0].saved == 0.0
    return "原价 12 < 实付 15，判定为脏数据"


@case("省多少钱：原价减实付")
def _():
    m = parse_menu_text("鸡腿堡\t12.9\t19.0")
    assert m.dishes[0].saved == 6.1, m.dishes[0].saved
    return "省 ¥6.10"


@case("用空格分隔也能认")
def _():
    m = parse_menu_text("麦辣鸡腿堡 12.9")
    assert len(m.dishes) == 1, m.dishes
    assert m.dishes[0].name == "麦辣鸡腿堡"
    assert m.dishes[0].price == 12.9
    return "「菜名 价格」空格写法"


@case("全角竖线和竖线都能当分隔符")
def _():
    a = parse_menu_text("鸡腿堡｜12.9")
    b = parse_menu_text("鸡腿堡|12.9")
    assert a.dishes[0].price == 12.9 and b.dishes[0].price == 12.9
    return "｜ 和 | 都认"


@case("¥ 和 元 会被剥掉")
def _():
    for raw in ("鸡腿堡\t¥12.9", "鸡腿堡\t12.9元", "鸡腿堡\t￥12.9元"):
        m = parse_menu_text(raw)
        assert m.dishes and m.dishes[0].price == 12.9, (raw, m.dishes)
    return "三种写法都得到 12.9"


@case("OCR 常见的中间点小数 12·9 也认")
def _():
    m = parse_menu_text("鸡腿堡\t12·9")
    assert m.dishes[0].price == 12.9, m.dishes[0].price
    return "12·9 → 12.9"


@case("界面标签不能当菜名")
def _():
    text = "起送\t20\n配送费\t3\n月售\t999\n满分\t5.0\n鸡腿堡\t12.9"
    m = parse_menu_text(text)
    names = [d.name for d in m.dishes]
    assert names == ["鸡腿堡"], names
    assert len(m.dropped) == 4, m.dropped
    return f"丢掉 4 条标签，只留鸡腿堡"


@case("没有价格的垃圾行要丢掉，不能编一个价")
def _():
    m = parse_menu_text("这一行根本不是菜品\n鸡腿堡\t12.9")
    assert len(m.dishes) == 1, m.dishes
    assert m.dropped == ["这一行根本不是菜品"], m.dropped
    return "认不出的行进 dropped，不猜价格"


@case("菜名里带数字不会把数字当价格")
def _():
    m = parse_menu_text("7-11 双人餐\t39.9")
    assert m.dishes[0].name == "7-11 双人餐", m.dishes[0].name
    assert m.dishes[0].price == 39.9
    return "7-11 保住整个菜名"


@case("空文本不炸，返回空菜单")
def _():
    m = parse_menu_text("")
    assert m.dishes == [] and m.total == 0.0
    assert "没从这段文本里认出菜品" in render_menu(m)
    return "空输入给出明确提示"


@case("渲染结果里有合计和原价对比")
def _():
    out = render_menu(parse_menu_text(REAL))
    assert "合计 ¥26.80" in out, out
    assert "省了 ¥12.10" in out, out
    return "合计 ¥26.80，标价上省 ¥12.10"


@case("渲染：认不出时的提示要带正确格式示例")
def _():
    out = render_menu(parse_menu_text("乱七八糟"))
    assert "菜名<Tab>价格" in out, out
    return "提示里给了可照抄的格式"


@case("转成外卖比价的一行：平台|小计")
def _():
    spec = to_offer_spec(parse_menu_text(REAL))
    assert spec == "美团|26.80", spec
    return spec


@case("转外卖比价：没来源时给占位平台名")
def _():
    spec = to_offer_spec(parse_menu_text("鸡腿堡\t12.9"))
    assert spec == "未知平台|12.90", spec
    return spec


@case("read_source：给文件路径就读文件，不碰剪贴板")
def _():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "menu.txt"
        p.write_text("鸡腿堡\t12.9", encoding="utf-8")
        assert "鸡腿堡" in read_source(str(p))
    return "读文件路径可用（测试不依赖系统剪贴板）"


@case("read_source：路径不存在时报错可读")
def _():
    try:
        read_source("D:\\绝对不存在的目录\\x.txt")
    except ClipboardError as e:
        assert "文件不存在" in str(e), str(e)
        return str(e)
    raise AssertionError("应该抛 ClipboardError")


@case("read_source：GBK 存的文件也能读")
def _():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "menu_gbk.txt"
        p.write_bytes("鸡腿堡\t12.9".encode("gbk"))
        assert "鸡腿堡" in read_source(str(p))
    return "记事本存的 GBK 文件不乱码"


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
