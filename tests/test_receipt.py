#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""截图识别与操作建议的自检。跑法：python tests/test_receipt.py

OCR 本身依赖系统，测试里不跑真实 OCR；这里测的是**解析容错**——
因为 OCR 一定会出错，解析必须扛得住。下面用真实 OCR 输出做样本。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.receipt import describe, normalize, parse_receipt  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


# 这是真实 OCR 输出（Windows 自带引擎，识别一张干净的模拟图）
REAL_OCR = """商 品 小 计 45 ． 佣
配 送 3 ． 00
包 装 1 ． 00
店 浦 满 减 一 8 ． 00
红 包 巧 ． 00
实 扌 36 ． 00"""


@case("归一化：全角转半角、去掉所有空白")
def _():
    assert normalize("商 品 小 计 45 ． 00") == "商品小计45.00"
    assert normalize("￥４５．００") == "¥45.00"
    assert normalize("－ 8") == "-8"


@case("真实 OCR 输出：主要字段要认出来")
def _():
    r = parse_receipt(REAL_OCR)
    assert r["items"] == 45.0, r
    assert r["delivery"] == 3.0, r
    # 「包装费」的「费」被 OCR 丢了，靠宽松关键词兜住
    assert r["packing"] == 1.0, r
    # 「店铺」被认成「店浦」，靠宽松匹配兜住
    assert r["shop_discount"] == 8.0, r
    # 「实付」的「付」被认成「扌」，靠「实」兜住
    assert r["final"] == 36.0, r


@case("OCR 认错的数字宁可留空，也不能填 0")
def _():
    # 「红包 巧 ． 00」：5 被认成「巧」，行里只剩 00。
    # 这时候填 0 会让人以为真的没有红包，比缺了更误导。
    r = parse_receipt(REAL_OCR)
    assert "red_packet" not in r, f"不该把认错的认成 0：{r}"


@case("干净的文本（手工粘贴）要全部认对")
def _():
    r = parse_receipt("""商品小计 ¥45.00
配送费 ¥3.00
包装费 ¥1.00
店铺满减 -¥8.00
红包 -¥5.00
实付 ¥36.00""")
    assert r == {
        "items": 45.0, "delivery": 3.0, "packing": 1.0,
        "shop_discount": 8.0, "red_packet": 5.0, "final": 36.0,
    }, r


@case("不同平台的叫法都要认")
def _():
    r = parse_receipt("""菜品小计 45.00
餐盒费 1.00
配送费 0.00
店铺优惠 10.00
优惠券 4.00
实付 32.00""")
    assert r["items"] == 45.0, r
    assert r["packing"] == 1.0, "餐盒费也是打包费"
    assert r["shop_discount"] == 10.0, r
    assert r["coupon"] == 4.0, r


@case("同类金额出现多次要累加")
def _():
    r = parse_receipt("商品小计 60.00\n红包 5.00\n红包 3.00\n实付 52.00")
    assert r["red_packet"] == 8.0, r


@case("认不出来就返回空，不能瞎猜")
def _():
    assert parse_receipt("随便一段没有金额的话") == {}
    assert parse_receipt("") == {}


@case("describe 能正常输出")
def _():
    text = describe({"items": 45, "delivery": 3})
    assert "菜品 45" in text and "配送 3" in text
    assert describe({}) == "什么都没认出来"


def main() -> int:
    passed = failed = 0
    print()
    for name, fn in CASES:
        try:
            fn()
            print(f"  ✓ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {name}")
            print(f"      {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {name}")
            print(f"      {type(e).__name__}: {e}")
            failed += 1
    print()
    print(f"  通过 {passed} / {passed + failed}")
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
