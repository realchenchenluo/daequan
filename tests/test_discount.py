#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「最多能省多少」的自检。跑法：python tests/test_discount.py

这一节的每一行都在盯钱：
  · 店铺满减和平台券该叠的必须叠上
  · 门槛按**原价小计**判（不是折后价）
  · 「最高抢66元」这种**上限**绝对不能当保底金额减下去
    （关注清单里真出过：45 元的单被算成 0 元）
  · 差几块钱就能用的券，要说出来而不是闷着
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.discount import (  # noqa: E402
    Promo,
    build_plan,
    parse_store_promos,
    plan_to_dict,
)
from coupon_hunter.models import Coupon as FetchedCoupon  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


# ── 从页面文字里认店铺优惠 ────────────────────────────

@case("店铺满减：常见写法都认")
def _():
    for raw in ("满30减5", "满 30 减 5", "满30元减5元", "满30减5元"):
        ps = parse_store_promos(raw)
        assert len(ps) == 1, (raw, ps)
        assert ps[0].kind == "满减"
        assert ps[0].threshold == 30.0 and ps[0].value == 5.0, ps[0]
    return "4 种写法都得到 满30减5"


@case("一句话里多条满减，全都认出来")
def _():
    ps = parse_store_promos("满30减5，满50减8，满80减15")
    got = sorted((p.threshold, p.value) for p in ps)
    assert got == [(30.0, 5.0), (50.0, 8.0), (80.0, 15.0)], got
    return "3 条"


@case("无门槛券：两种语序都认")
def _():
    a = parse_store_promos("5元无门槛")
    b = parse_store_promos("无门槛5元")
    assert a and a[0].kind == "无门槛" and a[0].value == 5.0, a
    assert b and b[0].kind == "无门槛" and b[0].value == 5.0, b
    return "「5元无门槛」「无门槛5元」都对"


@case("立减按无门槛处理")
def _():
    ps = parse_store_promos("新客立减10元")
    assert ps and ps[0].kind == "无门槛" and ps[0].value == 10.0, ps
    return "立减 10 元"


@case("折扣：8折 认成 0.8")
def _():
    ps = parse_store_promos("全场8折")
    assert ps and ps[0].kind == "折扣" and abs(ps[0].value - 0.8) < 1e-6, ps
    return "8折 → 0.8"


@case("折扣：只收 0.5~9.5 折")
def _():
    # 3 折是很狠的折扣，但它是真实存在的，不能拒
    three = [p for p in parse_store_promos("全场3折") if p.kind == "折扣"]
    assert three and abs(three[0].value - 0.3) < 1e-6, three
    # 10 折等于原价，12 折根本不存在 —— 一律不收
    for bad in ("全场10折", "12折", "全场20折"):
        assert not [p for p in parse_store_promos(bad) if p.kind == "折扣"], bad
    return "3折收，10折/12折/20折 拒"


@case("没有数字的推广语一条都不收（关键：不瞎猜）")
def _():
    for raw in ("限时特惠", "新人专享", "满减优惠", "大额补贴", "评价有礼"):
        assert parse_store_promos(raw) == [], f"「{raw}」被当成优惠了"
    return "5 种空话全部忽略"


@case("离谱面额丢掉：满5减100")
def _():
    assert parse_store_promos("满5减100") == []
    return "超过门槛 3 倍判为解析错误"


@case("重复的优惠只留一条")
def _():
    ps = parse_store_promos("满30减5 满30减5 满 30 减 5")
    assert len(ps) == 1, ps
    return "去重生效"


# ── 规划：数字必须对 ────────────────────────────────────

def _uni(title, threshold, value, value_is_max=False, platform="美团"):
    return FetchedCoupon(
        platform=platform, title=title, threshold=threshold, value=value,
        value_is_max=value_is_max, tag="口令券",
    )


@case("只有店铺满减：门槛到了就减")
def _():
    p = build_plan("美团", 45, delivery=3, packing=1,
                   store_promos=[Promo("满40减8", "满减", 40, 8)])
    assert p.result is not None
    assert p.result.food_after == 37.0, p.result.food_after
    assert p.final_price == 41.0, p.final_price
    assert p.max_discount == 8.0, p.max_discount
    return "45 → 37，加配送3+打包1 = 41.00，省 8.00"


@case("店铺满减 + 平台券：两个都要叠上")
def _():
    p = build_plan("美团", 60, delivery=3, packing=1,
                   store_promos=[Promo("满40减8", "满减", 40, 8)],
                   universal=[_uni("平台满50减6", 50, 6)])
    assert p.result.food_after == 46.0, p.result.food_after
    assert p.final_price == 50.0, p.final_price
    assert p.max_discount == 14.0, p.max_discount
    assert len(p.usable_universal) == 1
    return "60 − 8 − 6 = 46，加 4 = 50.00，省 14.00"


@case("平台券门槛没到就不算（45 元的单用不了满50）")
def _():
    p = build_plan("美团", 45, store_promos=[],
                   universal=[_uni("平台满50减6", 50, 6)])
    assert p.result.food_after == 45.0, p.result.food_after
    assert p.max_discount == 0.0
    assert "满50减6" in (p.result.unused and p.result.unused[0] or "") or p.result.unused
    return "满50减6 没用上，如实列出来"


@case("门槛按原价小计判：店铺减完后仍能用平台券")
def _():
    # 60 元单，店铺减 8 后是 52；平台券门槛 50 —— 按原价 60 判能用到，
    # 按折后 52 判也能用到。真正区分的是下面这条：
    p = build_plan("美团", 52, store_promos=[Promo("满40减8", "满减", 40, 8)],
                   universal=[_uni("平台满50减6", 50, 6)])
    assert p.result.food_after == 38.0, p.result.food_after
    return "52 原价够 50，减 8 再减 6 = 38"


@case("「最高抢66元」绝对不能当保底减（最重要的防护）")
def _():
    p = build_plan("美团", 45,
                   universal=[_uni("外卖节最高抢66元", 0, 66, value_is_max=True)])
    assert p.result.food_after == 45.0, f"被当成 66 元减下去了：{p.result.food_after}"
    assert p.max_discount == 0.0
    assert len(p.display_only) == 1
    assert any("上限" in w for w in p.warnings), p.warnings
    return "只展示，不参与计算，并明确告知"


@case("面额未知的券也不参与计算")
def _():
    c = FetchedCoupon(platform="美团", title="某活动券", threshold=None, value=None)
    p = build_plan("美团", 45, universal=[c])
    assert p.result.food_after == 45.0
    assert len(p.display_only) == 1
    return "没有面额就不猜"


@case("别的平台的券不能用在这单上")
def _():
    p = build_plan("美团", 45,
                   universal=[_uni("淘宝满40减10", 40, 10, platform="淘宝闪购")])
    assert p.usable_universal == [], p.usable_universal
    assert p.result.food_after == 45.0
    return "淘宝的券不会算进美团这一单"


@case("凑单建议：差一点就能用的券要提，并算清净赚多少")
def _():
    p = build_plan("美团", 45, store_promos=[],
                   universal=[_uni("平台满50减12", 50, 12)])
    assert p.top_up, "应该给出凑单建议"
    t = p.top_up[0]
    assert abs(t["gap"] - 5.0) < 1e-6, t
    assert abs(t["gain"] - 12.0) < 1e-6, t
    return "再买 5 元可用满50减12，净省 12.00"


@case("凑单：用了更小的券时，净赚要减掉已省的")
def _():
    p = build_plan("美团", 45, store_promos=[Promo("满40减8", "满减", 40, 8)],
                   universal=[_uni("平台满50减12", 50, 12)])
    t = p.top_up[0]
    assert abs(t["gap"] - 5.0) < 1e-6, t
    assert abs(t["gain"] - 4.0) < 1e-6, t  # 12 - 8
    return "凑单净省 4.00（12 减掉已在用的 8）"


@case("菜价是 0：不算，并说明原因")
def _():
    p = build_plan("美团", 0, store_promos=[Promo("满40减8", "满减", 40, 8)])
    assert p.result is None
    assert any("0" in w for w in p.warnings), p.warnings
    return "给出可操作的提示，不返回假数字"


@case("步骤里必须带「结算页为准」的提醒")
def _():
    p = build_plan("美团", 60, delivery=3,
                   store_promos=[Promo("满40减8", "满减", 40, 8)])
    joined = " ".join(p.steps)
    assert "结算页" in joined, joined
    assert any("规则" in w for w in p.warnings), p.warnings
    return "不会让人拿估算价去下单"


@case("有口令/链接的券，步骤里要给出怎么领")
def _():
    c1 = FetchedCoupon(platform="美团", title="外卖节", code="MT123",
                       threshold=40, value=6)
    c2 = FetchedCoupon(platform="美团", title="红包会场",
                       url="https://example.com/x", threshold=30, value=5)
    p = build_plan("美团", 60, universal=[c1, c2])
    joined = " ".join(p.steps)
    assert "MT123" in joined, joined
    assert "https://example.com/x" in joined, joined
    return "口令和链接都写进步骤"


@case("网页结构：字段齐全、能直接 json 序列化")
def _():
    import json

    p = build_plan("美团", 60, delivery=3, packing=1,
                   store_promos=[Promo("满40减8", "满减", 40, 8)],
                   universal=[_uni("平台满50减6", 50, 6)])
    d = plan_to_dict(p)
    s = json.dumps(d, ensure_ascii=False)
    assert "max_discount" in d and "steps" in d and "store_promos" in d
    assert d["max_discount"] == 14.0, d["max_discount"]
    assert d["final_price"] == 50.0, d["final_price"]
    assert len(d["store_promos"]) == 1
    return f"JSON {len(s)} 字节，序列化正常"


@case("店铺满减是分档的：只取其中一档，不能叠加")
def _():
    # 满30减5、满50减8 是同一档位体系的互斥选项，不该变成 5+8=13
    p = build_plan("美团", 60, store_promos=[
        Promo("满30减5", "满减", 30, 5),
        Promo("满50减8", "满减", 50, 8),
    ])
    assert p.result.food_after == 52.0, p.result.food_after
    return "60 只减 8（取更高一档），不是减 13"


@case("从 dict 还原：脏数据跳过，好的照常")
def _():
    from coupon_hunter.discount import promos_from_dicts
    raw = [
        {"text": "满30减5", "kind": "满减", "threshold": 30, "value": 5},
        {"text": "8折", "kind": "折扣", "threshold": 0, "value": 0.8},
        {"kind": "满减", "threshold": "坏", "value": "也坏"},
        {"kind": "奇怪的类型", "threshold": 10, "value": 2},
        "不是字典",
        None,
        {"kind": "无门槛", "value": 99999},
    ]
    got = promos_from_dicts(raw)
    assert len(got) == 2, got
    assert got[0].value == 5.0 and got[1].value == 0.8
    return "7 条脏输入里只留下 2 条合法的"


@case("从 dict 还原：空输入安全")
def _():
    from coupon_hunter.discount import promos_from_dicts
    assert promos_from_dicts(None) == []
    assert promos_from_dicts([]) == []
    return "None / [] 都返回空列表"


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
