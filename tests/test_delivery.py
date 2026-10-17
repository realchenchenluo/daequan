#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外卖到手价计算的自检。

跑法：python tests/test_delivery.py

这个模块的价值在于「算上配送费和券之后，哪个平台真便宜」——而外卖里
最容易算错的是**门槛按哪个数判**：平台券的门槛通常看商品原价小计，
不是看店铺满减减完之后的价格。写错会让本来能用的券被当成不能用，
直接把结论反过来。所以这条写死成用例。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.delivery import (  # noqa: E402
    Offer,
    compare,
    compute,
    parse_checkout_text,
    parse_share_text,
)
from coupon_hunter.stacking import Coupon  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


def _d(name, threshold, value, group="店铺券"):
    return Coupon(name, "满减", threshold, value, group)


@case("基本计算：门店满减 + 红包 + 配送费 + 打包费")
def _():
    o = Offer("美团", items=45, delivery=3, packing=1,
              shop_discounts=[_d("满40减8", 40, 8)], red_packet=5)
    r = compute(o)
    # 45 - 8 = 37，再减红包 5 = 32，+ 配送 3 + 打包 1 = 36
    assert r.food_after == 32, r.food_after
    assert r.final_price == 36, r.final_price


@case("平台券门槛按商品原价判，不是按满减之后（关键）")
def _():
    # 45 元的单，门店满40减10 之后只剩 35，
    # 但「满45减4」的平台券应该仍然可用——门槛看的是原价 45。
    o = Offer("淘宝闪购", items=45, delivery=0, packing=1,
              shop_discounts=[_d("满40减10", 40, 10, "店铺券")],
              coupons=[_d("满45减4", 45, 4, "平台券")],
              red_packet=3)
    r = compute(o)
    # 45 - 10 - 4 - 3 = 28，+ 打包 1 = 29
    assert r.food_after == 28, f"应 28，实际 {r.food_after}（平台券被误判成不可用？）"
    assert r.final_price == 29, r.final_price
    assert not r.unused, f"不该有券被浪费：{r.unused}"


@case("门槛真的不够时要判成不可用")
def _():
    o = Offer("美团", items=30, delivery=0, packing=0,
              coupons=[_d("满50减6", 50, 6, "平台券")])
    r = compute(o)
    assert r.final_price == 30
    assert r.unused and "满50减6" in r.unused[0]


@case("只看菜品价会选错平台（本功能的核心价值）")
def _():
    a = Offer("美团", items=40, delivery=5, packing=1,
              shop_discounts=[_d("满40减5", 40, 5)])
    b = Offer("淘宝闪购", items=45, delivery=0, packing=1,
              member=True, member_delivery_free=True,
              shop_discounts=[_d("满40减10", 40, 10)])
    ranked = compare([a, b])
    assert ranked[0].platform == "淘宝闪购", "应算出淘宝闪购更便宜"
    assert a.items < b.items, "而美团的菜品价其实更低——这正是容易选错的地方"
    # 美团 40-5+5+1 = 41；淘宝闪购 45-10+0+1 = 36
    assert ranked[0].final_price == 36, ranked[0].final_price
    assert ranked[1].final_price == 41, ranked[1].final_price


@case("会员免配送费")
def _():
    normal = Offer("美团", items=30, delivery=4, member=False)
    member = Offer("美团", items=30, delivery=4, member=True, member_delivery_free=True)
    assert compute(normal).final_price == 34
    assert compute(member).final_price == 30


@case("没有券时直接按 菜品+配送+打包")
def _():
    o = Offer("美团", items=20, delivery=3, packing=1)
    assert compute(o).final_price == 24


@case("从分享文本认店名")
def _():
    cases = [
        ("【肯德基(中关村店)】https://i.meituan.com/awp/xxx", "肯德基(中关村店)"),
        ("肯德基(中关村店) - 饿了么 https://h5.ele.me/xxx", "肯德基(中关村店)"),
        ("【海底捞火锅 三里屯店】京东外卖 满100减30 https://x.com", "海底捞火锅 三里屯店"),
        ("麦当劳(国贸店) 复制这条信息打开美团 https://i.meituan.com/x", "麦当劳(国贸店)"),
    ]
    for text, expect in cases:
        name, _url = parse_share_text(text)
        assert name == expect, f"{text[:30]} 得到 {name!r}，期望 {expect!r}"


@case("认不出店名时返回空，不能瞎猜")
def _():
    # 早先版本「剩下什么都当店名」，用户随手粘一句普通的话也会被显示成店名
    for text in ["https://i.meituan.com/awp/xxx", "随便一句没有店名的话", ""]:
        name, _url = parse_share_text(text)
        assert name == "", f"{text!r} 不该猜出店名，实际得到 {name!r}"


@case("分享文本里的链接要被抽出来")
def _():
    _name, url = parse_share_text("【某店】https://i.meituan.com/awp/abc123")
    assert url == "https://i.meituan.com/awp/abc123", url



@case("从结账页文本里认数字")
def _():
    text = """商品小计 ¥45.00
配送费 ¥3.00
包装费 ¥1.00
店铺满减 -¥8.00
红包 -¥5.00
实付 ¥36.00"""
    r = parse_checkout_text(text)
    assert r["items"] == 45.0, r
    assert r["delivery"] == 3.0, r
    assert r["packing"] == 1.0, r
    assert r["shop_discount"] == 8.0, f"折扣要取正数：{r}"
    assert r["red_packet"] == 5.0, r
    assert r["final"] == 36.0, r


@case("认数字：换个平台的说法也要认")
def _():
    r = parse_checkout_text("""菜品小计 ￥45.00
餐盒费 ￥1.00
配送费 ￥0.00
店铺优惠 -￥10.00
优惠券 -￥4.00
实付 ￥32.00""")
    assert r["items"] == 45.0, r
    assert r["packing"] == 1.0, "「餐盒费」也是打包费"
    assert r["shop_discount"] == 10.0, r
    assert r["coupon"] == 4.0, r


@case("认数字：多行同类金额要累加")
def _():
    r = parse_checkout_text("""商品小计 ¥60.00
红包 -¥5.00
红包 -¥3.00
实付 ¥52.00""")
    assert r["red_packet"] == 8.0, f"两个红包应累加成 8，实际 {r.get('red_packet')}"


@case("认数字：认不出来就返回空，不能瞎填")
def _():
    assert parse_checkout_text("随便一段没有金额的话") == {}
    assert parse_checkout_text("") == {}


@case("实付核对：一致时确认")
def _():
    pre = parse_checkout_text("商品小计 45.00\n配送费 3.00\n包装费 1.00\n店铺满减 8.00\n红包 5.00\n实付 36.00")
    o = Offer("美团", pre["items"], pre["delivery"], pre["packing"],
              [_d("满45减8", 45, 8)], [], pre["red_packet"],
              expected_final=pre["final"])
    r = compute(o)
    assert r.final_price == 36.0, r.final_price
    assert any("一致" in n for n in r.notes), r.notes


@case("实付核对：对不上时必须明确警告（这是最重要的一道保险）")
def _():
    # 平台规则和我们的假设不同时，算出来的价会和平台显示的实付不一致。
    # 规则没有公开文档、我们是按常见做法假设的，所以必须把这个差异说出来，
    # 而不是装作算准了。
    o = Offer("某平台", items=50, delivery=4, packing=1,
              shop_discounts=[_d("满50减5", 50, 5)], expected_final=40.0)
    r = compute(o)
    assert r.final_price != 40.0
    assert any("对不上" in n and "以平台为准" in n for n in r.notes), r.notes

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
