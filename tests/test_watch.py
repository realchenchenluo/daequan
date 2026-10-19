#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
关注清单的自检。跑法：python tests/test_watch.py

这里最要紧的一条是「抓来的券不能当钱用」——券源只给标题，
面额是从标题里猜的，而且常是「最高抢66元」这种上限。
早先版本直接拿它当无门槛券减，45 元的单被算成 0 元。
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 把数据目录指到临时位置，别污染真实的 data/
_TMP = Path(tempfile.mkdtemp(prefix="watchtest_"))
import os  # noqa: E402

os.environ["COUPON_HUNTER_DATA"] = str(_TMP)

from coupon_hunter import watch  # noqa: E402
from coupon_hunter.models import Coupon as FetchedCoupon  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


@case("加、查、删")
def _():
    watch.clear()
    watch.add(watch.WatchItem(name="A", prices={"京东": 100}, target=90))
    watch.add(watch.WatchItem(name="B", prices={"京东": 200}))
    items = watch.load()
    assert len(items) == 2, len(items)

    # 同名应替换，不该重复
    watch.add(watch.WatchItem(name="A", prices={"京东": 111}, target=90))
    items = watch.load()
    assert len(items) == 2, f"同名没被替换：{len(items)}"
    a = next(i for i in items if i.name == "A")
    assert a.prices["京东"] == 111

    assert watch.remove("A") is True
    assert watch.remove("不存在") is False
    assert len(watch.load()) == 1


@case("基本计算：价格 → 减券 → 加配送打包")
def _():
    watch.clear()
    watch.add(watch.WatchItem(
        name="外卖单", kind="外卖", prices={"美团": 45}, target=36,
        coupons={"美团": ["满减,45,10"]},
        fees={"美团": {"delivery": 3, "packing": 1}},
    ))
    r = watch.check_all([])[0]
    # 45 - 10 + 3 + 1 = 39
    assert r.best_price == 39.0, r.best_price
    assert r.best_platform == "美团"


@case("达到目标价要标记出来")
def _():
    watch.clear()
    watch.add(watch.WatchItem(name="便宜货", prices={"拼多多": 50}, target=60))
    r = watch.check_all([])[0]
    assert r.hit is True, r
    assert r.best_price == 50.0


@case("没达到目标价不标记")
def _():
    watch.clear()
    watch.add(watch.WatchItem(name="贵的", prices={"京东": 500}, target=400))
    r = watch.check_all([])[0]
    assert r.hit is False
    assert r.best_price == 500.0


@case("多个平台选最便宜的")
def _():
    watch.clear()
    watch.add(watch.WatchItem(name="多平台", prices={"京东": 399, "拼多多": 359, "淘宝": 379}))
    r = watch.check_all([])[0]
    assert r.best_platform == "拼多多", r.best_platform
    assert r.best_price == 359.0


@case("抓来的券不能当钱用（这是最重要的防护）")
def _():
    # 券源只给标题，面额是从「最高抢66元」这种标题里猜的，是上限不是保底。
    # 早先版本直接拿它减，45 元的单被算成 0 元。
    watch.clear()
    watch.add(watch.WatchItem(name="外卖", kind="外卖", prices={"淘宝闪购": 45}))
    fetched = [FetchedCoupon(
        platform="淘宝闪购",
        title="淘宝闪购-天天领红包(全场景, 最高抢66元大额红包)",
        value=66.0, value_is_max=True,
    )]
    r = watch.check_all(fetched)[0]
    assert r.best_price == 45.0, f"抓来的券不该参与计算，实际算出 {r.best_price}"
    assert r.available_coupons, "但应该把它作为参考列出来"


@case("目标价排序：命中的排前面")
def _():
    watch.clear()
    watch.add(watch.WatchItem(name="没命中", prices={"京东": 500}, target=100))
    watch.add(watch.WatchItem(name="命中了", prices={"京东": 90}, target=100))
    results = watch.check_all([])
    assert results[0].name == "命中了", [r.name for r in results]


@case("没有价格的条目不崩")
def _():
    watch.clear()
    watch.add(watch.WatchItem(name="空条目"))
    r = watch.check_all([])[0]
    assert r.best_price is None
    assert "没有可比的价格" in r.summary()


@case("报告能正常渲染")
def _():
    watch.clear()
    watch.add(watch.WatchItem(name="X", prices={"京东": 100}, target=90))
    text = watch.render_report(watch.check_all([]))
    assert "关注清单检查" in text
    assert "X" in text


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
