#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商家列表解析的自检。跑法：python tests/test_storelist.py

测试数据全部来自 2026-10 从美团外卖 H5 首页**真实读出来的文字**，
不是编的。真实页面的坑都在这份数据里：
  · 店名和一堆短标签混在一起，没有分隔符
  · 有的店有人均价，有的没有
  · 有的店没有「美团专送」标签
  · 顶部有分类标签（异国料理/小吃馆…）和定位提示，都不是店名
  · 底部有「首页/订单/我的」导航，也不是店名
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.storelist import Store, parse_store_list, render_stores  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


# 美团外卖 H5 首页（无登录）真实文字
REAL_HOME = """草场地国际艺术村
点击授权获取精确定位信息
开启定位才能看到附近的商家哦~
去开启
搜索
异国料理
小吃馆
家常菜
晚餐优选
点评高分
优惠商家
满减优惠
品牌商家
高济百康药房（蒋台路分店）
5.0分
月售9999+
美团专送
起送 ¥20
配送 约¥3.5
34分钟
3.5km
“不卖临期药”
111医药馆（酒仙桥店）
4.8分
月售4000+
美团专送
起送 ¥20
配送 约¥1
25分钟
2.6km
“商家态度好”
百康药房（康民湖光中街店）
4.9分
月售8000+
美团专送
起送 ¥20
配送 约¥5
31分钟
4.3km
“商家态度好”
窑鸡王(望京店)
4.4分
月售1000+
人均 ¥39
起送 ¥0
配送 约¥2.9
53分钟
3.8km
“啃起来特别过瘾”
BossLi·高压锅盖码饭（望京店）
4.7分
月售4000+
人均 ¥24
起送 ¥0
配送 约¥0
30分钟
2.7km
望京盖浇饭热销榜第2名
正在加载...
首页
订单
我的"""


@case("真实首页：认出 5 家店")
def _():
    stores = parse_store_list(REAL_HOME)
    assert len(stores) == 5, f"应该 5 家，实际 {len(stores)}：{[s.name for s in stores]}"
    names = [s.name for s in stores]
    assert names[0] == "高济百康药房（蒋台路分店）", names[0]
    assert names[-1] == "BossLi·高压锅盖码饭（望京店）", names[-1]
    return f"5 家：{', '.join(names)}"


@case("真实首页：字段逐项对上")
def _():
    stores = parse_store_list(REAL_HOME)
    a = stores[0]
    assert a.rating == 5.0, a.rating
    assert a.monthly_sales == "9999+", a.monthly_sales
    assert a.delivery_mode == "美团专送", a.delivery_mode
    assert a.min_order == 20.0, a.min_order
    assert a.delivery_fee == 3.5, a.delivery_fee
    assert a.eta_min == 34, a.eta_min
    assert a.distance_km == 3.5, a.distance_km
    assert a.quote == "不卖临期药", a.quote
    assert a.avg_price is None, a.avg_price
    return "店名/评分/月售/起送/配送/分钟/km/点评语 全对"


@case("真实首页：人均价只在有的店上出现")
def _():
    stores = parse_store_list(REAL_HOME)
    assert stores[3].avg_price == 39.0, stores[3].avg_price
    assert stores[4].avg_price == 24.0, stores[4].avg_price
    assert stores[1].avg_price is None
    return "窑鸡王 39 / BossLi 24 / 药店没有人均价"


@case("真实首页：榜单名不吞进店名")
def _():
    stores = parse_store_list(REAL_HOME)
    assert stores[4].rank == "望京盖浇饭热销榜第2名", stores[4].rank
    assert "榜" not in stores[4].name, stores[4].name
    return "榜单单独存，店名还是 BossLi"


@case("分类标签和底部导航不当成店")
def _():
    names = [s.name for s in parse_store_list(REAL_HOME)]
    for bad in ("异国料理", "小吃馆", "搜索", "首页", "订单", "我的", "正在加载..."):
        assert bad not in names, f"「{bad}」被当成店名了"
    return "8 个干扰项全部排除"


@case("空文本不炸")
def _():
    assert parse_store_list("") == []
    assert parse_store_list("\n\n  \n") == []
    return "空输入返回空列表"


@case("只有详情行没有店名：不瞎造店")
def _():
    txt = "5.0分\n月售100+\n起送 ¥20\n配送 约¥3"
    stores = parse_store_list(txt)
    assert stores == [], f"不该认出店：{[s.name for s in stores]}"
    return "没有店名的孤儿详情行被丢掉"


@case("纯数字行不当成店名")
def _():
    txt = "12345\n5.0分\n起送 ¥20"
    stores = parse_store_list(txt)
    assert not any(s.name == "12345" for s in stores)
    return "纯数字被拒"


@case("起送 0 元能读出来（不是 None）")
def _():
    stores = parse_store_list("某店\n4.5分\n起送 ¥0\n配送 约¥2")
    assert stores[0].min_order == 0.0, stores[0].min_order
    return "起送¥0 → 0.0，不是 None"


@case("配送费 0 元能读出来")
def _():
    stores = parse_store_list(REAL_HOME)
    assert stores[4].delivery_fee == 0.0, stores[4].delivery_fee
    return "BossLi 配送¥0 → 0.0"


@case("饿了么写法：反过来的「¥20起送」也认")
def _():
    stores = parse_store_list("老王面馆\n4.6分\n¥15起送\n配送 2\n28分钟\n1.2km")
    assert stores[0].min_order == 15.0, stores[0].min_order
    assert stores[0].delivery_fee == 2.0, stores[0].delivery_fee
    return "¥15起送 / 配送 2 都认出来了"


@case("店名里的数字不会被当成评分")
def _():
    stores = parse_store_list("7-11便利店（望京店）\n4.3分\n月售500+\n起送 ¥10\n配送 约¥1")
    assert stores[0].name == "7-11便利店（望京店）", stores[0].name
    assert stores[0].rating == 4.3, stores[0].rating
    return "7-11 保住整个名字，没被拆成 7 和 11"


@case("两页拼在一起也不串店")
def _():
    txt = "甲店\n4.0分\n起送 ¥10\n乙店\n3.9分\n起送 ¥15"
    stores = parse_store_list(txt)
    assert [s.name for s in stores] == ["甲店", "乙店"], [s.name for s in stores]
    assert stores[0].min_order == 10.0 and stores[1].min_order == 15.0
    return "甲=10 / 乙=15，没互相污染"


@case("渲染：空结果给明确提示")
def _():
    out = render_stores([], "不存在的店")
    assert "没找到" in out and "不存在的店" in out, out
    return out.splitlines()[0]


@case("渲染：挑出配送最便宜的店")
def _():
    out = render_stores(parse_store_list(REAL_HOME), "")
    assert "配送最便宜" in out, out
    assert "BossLi" in out.split("配送最便宜")[1], out
    return "配送¥0 的 BossLi 被指出来"


@case("渲染：单店不崩")
def _():
    out = render_stores([Store(name="孤店")], "")
    assert "孤店" in out
    return "只有名字的店也能渲染"


@case("渲染：全是 None 的店不出现 nan")
def _():
    out = render_stores([Store(name="无数据店")], "")
    assert "None" not in out and "nan" not in out, out
    return "字段缺失时不打印 None/nan"


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
