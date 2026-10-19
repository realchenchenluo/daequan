#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品页截图解析的自检。跑法：python tests/test_product.py

用真实截图的 OCR 输出做样本 —— 真实截图比合成的测试图难得多，
这些用例都是从实际踩出来的坑。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.product import (  # noqa: E402
    _split_block,
    describe_product,
    parse_product_blocks,
    parse_product_page,
)

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


@case("三个数字矛盾时，用算术关系纠正并报警")
def _():
    # 19.5 + 5 = 24.5 ≠ 29.8，说明原价读错了。
    # 工具的取舍：以「现价+立省」为准（这两个是用户最关心的数），
    # 并把 OCR 读到的原价差异说出来。
    info = parse_product_page("一口价 ¥19.5\n原价 ¥29.8\n立省 ¥5")
    assert info["original"] == 24.5, f"应按 现价+立省 算出 24.5，实际 {info.get('original')}"
    assert any("已按后者算" in s for s in info["suspicious"]), info["suspicious"]


@case("原价由 现价+立省 推出（不依赖 OCR 读第三个数）")
def _():
    # 实测：「￥29.8 1月售300+」去空格后粘成「29.81」，OCR 会读错 0.01
    info = parse_product_page("一口价 ¥19.5\n立省 ¥10.3\n原价 ¥29.81")
    assert info["original"] == 29.8, f"应纠正为 29.8，实际 {info.get('original')}"
    assert info["price"] == 19.5 and info["saved"] == 10.3


@case("原价比现价低时不硬算负数立省")
def _():
    info = parse_product_page("一口价 ¥50\n原价 ¥30")
    assert "saved" not in info, f"不该推出负的立省：{info.get('saved')}"
    assert any("不比现价" in s for s in info["suspicious"])


@case("什么都没有时不崩、不乱猜")
def _():
    info = parse_product_page("随便一段没有价格的话")
    assert "price" not in info
    assert "merchant" not in info
    assert "没认出有效信息" in describe_product(info)



# ── 以下是「真实截图版式」的回归用例 ──
# 合成 blocks：(text, x, y, w, h)，坐标按真实截图的比例估的。
# 这些用例对应 5 张真实美团/京东截图，覆盖了踩过的所有坑。

@case("块内多标签：金额要归给正确的标签")
def _():
    # 京东的「一口价|已补￥7.1」：7.1 是已补，不是现价
    r = _split_block("一口价「已补￥7.1")
    kinds = [k for k, _v, _p in r]
    assert "save" in kinds and "price" not in kinds, r

    # 「一口价￥15.9」这种正常的，要认成价格
    r2 = _split_block("一口价￥15.9")
    assert ("price", 15.9, 8) in [(k, v, p) for k, v, p in r2], r2


@case("金额在标签前面时不认（避免把合计当成券后价）")
def _():
    # 「￥44.8 券后约」：44.8 是前面的合计，券后价在另一个块里
    r = _split_block("￥44.8券后约！")
    assert r == [], r


@case("噪音数字不当价格（「一口价1已补$25.3」里的 1 是竖线）")
def _():
    r = _split_block("一口价1已补￥25.3")
    prices = [v for k, v, _p in r if k == "price"]
    assert 1.0 not in prices, f"把竖线认成了 1 元：{r}"


@case("京东版式：现价在标签左边，已补算优惠")
def _():
    blocks = [
        ("￥10.9起",        38, 1465, 120, 40),
        ("一口价1已补￥7.1", 242, 1480, 300, 40),
        ("￥18",             45, 1549, 80, 40),
        ("【B老吃家私藏】单人吃饱2件套", 148, 1764, 500, 40),
    ]
    r = parse_product_blocks(blocks)
    assert r.get("price") == 10.9, r
    assert r.get("saved") == 7.1, r
    assert r.get("original") == 18.0, r


@case("券后价比一口价更该采用（香辣鸡架版式）")
def _():
    blocks = [
        ("28.47",        180, 1102, 120, 44),
        ("折后价！",       47, 1140, 120, 44),
        ("¥33.5",         46, 1207, 90, 36),
        ("香辣鸡架（整只）", 52, 1290, 300, 44),
        ("￥44.8券后约！", 187, 2213, 260, 40),
        ("￥24.8^",       390, 2201, 90, 36),
    ]
    r = parse_product_blocks(blocks)
    assert r.get("price") == 24.8, f"应取券后价 24.8，实际 {r.get('price')}"
    assert r.get("original") == 33.5, r


@case("图片里的 logo 文字不能当商品名")
def _():
    blocks = [
        ("百事可乐",      845, 1082, 150, 40),   # 瓶身 logo，在价格上方
        ("￥11.1起",       38, 1463, 120, 40),
        ("一口价1已补￥25.3", 223, 1479, 300, 40),
        ("￥36.4",         45, 1548, 90, 40),
        ("豪横小食随心选",  52, 1764, 300, 44),
    ]
    r = parse_product_blocks(blocks)
    assert r.get("product") == "豪横小食随心选", f"实际 {r.get('product')!r}"

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
