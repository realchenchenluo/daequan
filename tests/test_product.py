#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品页截图解析的自检。跑法：python tests/test_product.py

用真实截图的 OCR 输出做样本 —— 真实截图比合成的测试图难得多，
这些用例都是从实际踩出来的坑。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.product import describe_product, parse_product_page  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


# Windows 自带 OCR 读一张真实美团商品页截图的结果
WIN_OCR = """糕 研 社
一 囗 价 ￥ 19 · 5
立 省 ￥ 1a3
￥ 29g 月 售 30 囗 +
您 盐 芝 士 蛋 糕 （ 超 清 爽 ）"""

# tesseract.js 读同一张图的结果（更烂一些）
JS_OCR = """一 0 价 y19.5 有 ETE 神 抢 手
海盐 艺 士 蛋 炉 ( 超 请 更 ) 加 入 购物 车
推荐 买 贵 必 赔 .20+ 回 尖 客 推荐 22 人 党 得 味道 更"""


@case("Windows OCR：能救的都救回来")
def _():
    info = parse_product_page(WIN_OCR)
    assert info.get("price") == 19.5, f"「一囗价￥19·5」应读出 19.5，实际 {info}"
    assert info.get("merchant") == "糕研社", info.get("merchant")


@case("Windows OCR：读不出来的数字要明确标出，不能瞎猜")
def _():
    info = parse_product_page(WIN_OCR)
    # 「立省￥1a3」里 10.3 被认成 1a3，不能截成 1 或 3
    assert "saved" not in info, f"不该猜出立省金额：{info.get('saved')}"
    assert any("立省" in s and "认错" in s for s in info["suspicious"]), info["suspicious"]


@case("tesseract.js：一口价被认成「一0价 y19.5」也能读出价格")
def _():
    info = parse_product_page(JS_OCR)
    assert info.get("price") == 19.5, f"实际 {info}"


@case("干净文本：四个字段全对")
def _():
    info = parse_product_page("糕研社\n一口价 ¥19.5\n原价 ¥29.8\n立省 ¥10.3")
    assert info["merchant"] == "糕研社"
    assert info["price"] == 19.5
    assert info["original"] == 29.8
    assert info["saved"] == 10.3
    assert not info["suspicious"], info["suspicious"]


@case("数字和字母混在一起时整段作废（关键防护）")
def _():
    # 「¥1a3」不能截成 1 —— 那会让用户以为只省了 1 块钱
    info = parse_product_page("立省 ¥1a3")
    assert "saved" not in info
    # 「¥29g」同理
    info2 = parse_product_page("原价 ¥29g")
    assert "original" not in info2


@case("不把时间当价格（21:05 那行）")
def _():
    # 实测踩过：状态栏的「21:05」被当成原价 21
    info = parse_product_page("21:05\n一口价 ¥19.5\n21:08")
    assert info.get("price") == 19.5
    assert "original" not in info, f"不该把时间当原价：{info.get('original')}"


@case("商家名：挡住 OCR 头部噪声")
def _():
    # 「和S于」是真实的 OCR 乱码，不能当商家名
    assert "merchant" not in parse_product_page("和S于\n一口价¥19.5")
    # 三个汉字的正常店名要认出来
    assert parse_product_page("糕研社\n一口价¥19.5").get("merchant") == "糕研社"
    # 两个字且无拉丁字母也认
    assert parse_product_page("蜜雪\n一口价¥19.5").get("merchant") == "蜜雪"


@case("原价和现价逻辑矛盾时要报警")
def _():
    info = parse_product_page("一口价 ¥50\n原价 ¥30")
    assert any("不比现价" in s for s in info["suspicious"]), info["suspicious"]


@case("原价−立省≠现价要报警")
def _():
    info = parse_product_page("一口价 ¥19.5\n原价 ¥29.8\n立省 ¥5")
    # 29.8 - 5 = 24.8 ≠ 19.5
    assert any("对不上" in s for s in info["suspicious"]), info["suspicious"]


@case("什么都没有时不崩、不乱猜")
def _():
    info = parse_product_page("随便一段没有价格的话")
    assert "price" not in info
    assert "merchant" not in info
    assert "没认出有效信息" in describe_product(info)


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
