#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优惠叠加计算引擎的自检。

跑法：python tests/test_stacking.py

为什么单独写这个文件：这个引擎算的是「你到底付多少钱」，算错了比不算更糟。
它的几个坑（顺序影响结果、国补基数、减到 0 被重置、自定义类别被丢掉）
都是实测踩出来的，写死成用例免得以后改代码时又踩回去。

**没有依赖**：不用装 pytest，直接跑。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.stacking import (  # noqa: E402
    PLATFORM_RULES,
    Coupon,
    best,
    suggest_topup,
)

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


# ──────────────────────────────────────────────────────────

@case("顺序确实影响结果（8折券 + 满100减20）")
def _():
    # 折扣券的 value 是「付多少比例」：8 折 = 0.8
    c8 = Coupon("8折券", "折扣", value=0.8, exclusive_group="折扣券")
    c20 = Coupon("满100减20", "满减", threshold=100, value=20, exclusive_group="平台券")
    r = best(100, [c8, c20], "京东自营")
    # 京东顺序：平台券先 → 100-20=80 → 80 也能打 8 折 → 64
    assert r.final_price == 64, f"应 64，实际 {r.final_price}"
    # 反过来先打折：100*0.8=80，此时不满 100，满减用不了 → 80
    # 所以 64 是更优，且平台默认顺序恰好就是 64
    assert r.optimized_price == 64
    assert not r.order_matters


@case("同类券互斥，自动用省得最多的那张")
def _():
    a = Coupon("平台券 满100减20", "满减", 100, 20, "平台券")
    b = Coupon("平台券 满100减30", "满减", 100, 30, "平台券")
    r = best(100, [a, b], "京东自营")
    assert r.final_price == 70, f"应 70，实际 {r.final_price}"
    assert any("满100减20" in u for u in r.unused), "没用的那张应出现在 unused 里"


@case("国补必须排在最后（它是支付时才算的）")
def _():
    gb = Coupon("国补15%", "补贴", value=0.15, exclusive_group="国补")
    c100 = Coupon("满1000减100", "满减", 1000, 100, "平台券")
    r = best(2000, [gb, c100], "京东自营")
    # (2000-100)*0.85 = 1615 —— 这才是实际能付到的
    assert r.final_price == 1615, f"应 1615，实际 {r.final_price}"
    # 而如果顺序可调把国补挪到前面：(2000*0.85)-100 = 1600，更便宜但做不到
    assert r.optimized_price == 1600, f"optimized 应 1600，实际 {r.optimized_price}"
    assert r.order_matters, "应提示顺序有讲究"


@case("不在平台规则里的类别不能被丢掉")
def _():
    # 这条是修掉的真 bug：类别不认识时早先版本会跳过，导致报价偏高
    cs = [Coupon(f"券{i}", "无门槛", value=1, exclusive_group=f"自定义组{i}") for i in range(3)]
    r = best(100, cs, "通用")
    assert r.final_price == 97, f"应 97，实际 {r.final_price}"


@case("资质不够时跳过（Plus）")
def _():
    plus = Coupon("Plus 满500减30", "会员", 500, 30, "会员满减", requires="plus")
    assert best(600, [plus], "京东自营", has=set()).final_price == 600
    assert best(600, [plus], "京东自营", has={"plus"}).final_price == 570


@case("拼多多四件套顺序")
def _():
    cs = [
        Coupon("百亿补贴", "无门槛", value=50, exclusive_group="百亿补贴"),
        Coupon("平台券 满200减20", "满减", 200, 20, "平台券"),
        Coupon("红包5元", "无门槛", value=5, exclusive_group="红包"),
    ]
    r = best(300, cs, "拼多多")
    assert r.final_price == 225, f"应 225，实际 {r.final_price}"


@case("价格被减到 0 时不能被重置回原价")
def _():
    # 这条也是修掉的真 bug：早先用 `if not res.final_price` 兜底，
    # 而 0 是合法结果，结果被当成「没算」重置了
    c = Coupon("满10减30", "满减", 10, 30, "平台券")
    r = best(10, [c], "京东自营")
    assert r.final_price == 0, f"应 0，实际 {r.final_price}"


@case("边界：没有券 / 未知平台 / 超排列上限")
def _():
    assert best(100, [], "京东自营").final_price == 100

    a = Coupon("平台券 满100减20", "满减", 100, 20, "平台券")
    assert best(100, [a], "不存在的平台").final_price == 80, "未知平台应走通用规则"

    big = [Coupon(f"券{i}", "无门槛", value=1, exclusive_group=f"组{i}") for i in range(10)]
    assert best(100, big, "通用").final_price == 90, "超过排列上限时不该崩"


@case("凑单建议：值不值得凑要算清楚")
def _():
    t1 = suggest_topup(260, [Coupon("满300减50", "满减", 300, 50, "平台券")])
    assert t1 and "值得凑" in t1[0], f"应判为值得凑：{t1}"

    t2 = suggest_topup(95, [Coupon("满100减5", "满减", 100, 5, "平台券")])
    assert t2 and "不划算" in t2[0], f"应判为不划算：{t2}"


@case("平台规则表结构完整")
def _():
    for name, rule in PLATFORM_RULES.items():
        assert rule.get("order"), f"{name} 缺 order"
        assert rule.get("desc"), f"{name} 缺 desc"
        assert rule.get("sources"), f"{name} 缺 sources（规则要有出处）"


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
