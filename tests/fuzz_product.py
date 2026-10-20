#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品页解析的模糊测试（1000 例）。

思路：真实截图我只拿到 5 张，不够用。所以以那 5 张的真实版式为模板，
程序化生成大量变体，每个变体都带「正确答案」，再让解析器去跑。

变体覆盖：
  · 4 种真实版式（美团一口价 / 美团神券价 / 京东已补 / 券后价）
  · OCR 常见错字（0↔O、1↔l、5↔S、8↔g、·↔.、全角标点）
  · 标签同义换写（一口价/现价/折后价/神券价/券后约）
  · 噪音行（状态栏时间、通知数、月售、评价数、促销文案）
  · 字段缺失（没有原价、没有优惠额）
  · 数字前后粘连（¥29.8 1月售300+ → 29.81）

判定标准（关键）：
  · **现价必须对**——这是用户唯一真正在意的数
  · 原价/优惠额：允许由算术推出（现价+优惠=原价），只要三者自洽即可
  · 如果某个数被 OCR 认坏了，解析器**必须报警**，不能悄悄给个错的

跑法：python tests/fuzz_product.py [次数]
"""

import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.product import parse_product_page  # noqa: E402

# ──────────────────────────────────────────────────────────
# 生成器
# ──────────────────────────────────────────────────────────

PRICE_LABELS = ["一口价", "现价", "折后价", "神券价", "特价", "活动价", "售价"]
SAVE_LABELS = ["立省", "已省", "已补"]
ORIG_LABELS = ["原价", "划线价", "市场价"]

# OCR 常见数字误识（用于制造「认坏」的样本）
DIGIT_NOISE = {"0": "O", "1": "l", "5": "S", "8": "g", "9": "q", "6": "b"}

NOISE_LINES = [
    "23:11", "72%", "5G", "MB/S", "98",
    "月售400+", "月售0", "近1周10万+人浏览",
    "推荐 买贵必赔 20+回头客推荐",
    "商品评价(7)", "查看全部>",
    "限时抢购", "1.11低价热卖", "超级补贴",
    "免打包费 免必选品", "京东秒送 约35分钟",
]


def _fmt(v: float) -> str:
    """按真实页面的写法格式化金额：整数不带小数，否则保留 1-2 位。"""
    if float(v) == int(v):
        return str(int(v))
    return f"{v:g}"


def _corrupt_number(text: str, rng: random.Random) -> str:
    """把一个数字串弄坏（模拟 OCR 认错）。"""
    chars = list(text)
    idx = [i for i, c in enumerate(chars) if c.isdigit()]
    if not idx:
        return text
    i = rng.choice(idx)
    chars[i] = DIGIT_NOISE.get(chars[i], "x")
    return "".join(chars)


def make_case(rng: random.Random) -> dict:
    """造一个用例。返回 {kind, lines, expect, note}。"""
    kind = rng.choice(["meituan", "meituan_coupon", "jd", "coupon_after"])

    # 价格：整数或一位小数，落在合理区间
    price = round(rng.choice([9.9, 10.9, 11.1, 12.5, 15, 15.9, 19.5, 24.8,
                              25, 28.47, 35, 39.9, 45, 58, 68, 88]), 2)
    saved = round(rng.choice([3, 5, 6, 7.1, 8.7, 10.3, 12, 15, 20, 25.3]), 2)
    original = round(price + saved, 2)

    lines: list[str] = []
    expect = {"price": price, "original": original, "saved": saved}
    note = ""

    if kind == "meituan":
        label = rng.choice(PRICE_LABELS)
        lines.append(f"{label}￥{_fmt(price)}")
        lines.append(f"{rng.choice(SAVE_LABELS)}￥{_fmt(saved)}")
        lines.append(f"￥{_fmt(original)}1月售{rng.randint(0, 999)}+")

    elif kind == "meituan_coupon":
        lines.append(f"{rng.choice(['神券价', '一口价'])}￥{_fmt(price)}")
        lines.append(f"{rng.choice(SAVE_LABELS)}￥{_fmt(saved)}")
        lines.append(f"￥{_fmt(original)} 1月售{rng.randint(0, 500)}")

    elif kind == "jd":
        # 京东：¥X起 / 一口价|已补¥Y / ¥Z
        lines.append(f"￥{_fmt(price)}起")
        lines.append(f"一口价|{rng.choice(['已补', '补贴'])}￥{_fmt(saved)}")
        lines.append(f"￥{_fmt(original)}")
        # 京东页面还有一行「1.11低价热卖」，很容易被误认成价格
        lines.append("1.11低价热卖")

    else:  # coupon_after
        # 折后价（可能是 price），券后约（也是 price），这里统一两处都给 price
        lines.append(_fmt(price))
        lines.append("折后价！")
        lines.append(f"¥{_fmt(original)}")
        lines.append(f"￥{_fmt(original)}券后约！")
        lines.append(f"￥{_fmt(price)}^")
        lines.append("已减20 再买7.2再减1 凑单>")

    # 打乱噪音行
    for _ in range(rng.randint(0, 3)):
        lines.insert(rng.randint(0, len(lines)), rng.choice(NOISE_LINES))

    # 随机加点空格（OCR 常在字间插空格）
    if rng.random() < 0.35:
        lines = [" ".join(ch if ch != " " else "" for ch in l) for l in lines]

    # 随机制造一类「认坏」的字段
    roll = rng.random()
    if roll < 0.25:
        # 弄坏优惠额：应该能由 原价-现价 推出来
        for i, l in enumerate(lines):
            if any(k in l for k in SAVE_LABELS):
                lines[i] = _corrupt_number(l, rng)
                note = "优惠额被认坏"
                break
    elif roll < 0.40:
        # 弄坏原价：应该能由 现价+优惠 推出来
        for i, l in enumerate(lines):
            if any(k in l for k in ORIG_LABELS) or (
                l.startswith("￥") and _fmt(original) in l and _fmt(price) not in l
            ):
                lines[i] = _corrupt_number(l, rng)
                note = "原价被认坏"
                break
    elif roll < 0.50:
        # 弄坏现价：解析器**必须报警**，不能给出一个错数。
        # 注意：京东版式的现价在「¥X起」那一行，不在标签行里，
        # 所以要按版式找到正确的那一行再弄坏（这里曾经写错，导致误报）。
        target = None
        if kind == "jd":
            # 京东：现价在「¥X起」那一行
            for i, l in enumerate(lines):
                if _fmt(price) in l and "起" in l:
                    target = i
                    break
        elif kind == "coupon_after":
            # 券后版式：现价是单独一行的裸数字（「折后价！」那行没有数字）
            for i, l in enumerate(lines):
                if l.strip() == _fmt(price):
                    target = i
                    break
        if target is None:
            for i, l in enumerate(lines):
                if any(k in l for k in PRICE_LABELS) and re.search(r"\d", l):
                    target = i
                    break
        if target is None:
            for i, l in enumerate(lines):
                if any(k in l for k in PRICE_LABELS):
                    target = i
                    break
        if target is not None:
            lines[target] = _corrupt_number(lines[target], rng)
            expect["price"] = None      # 允许认不出
            expect["must_warn"] = True  # 但必须提示
            note = "现价被认坏"

    return {
        "kind": kind,
        "lines": lines,
        "expect": expect,
        "note": note,
    }


# ──────────────────────────────────────────────────────────
# 校验
# ──────────────────────────────────────────────────────────

def check(case: dict) -> str | None:
    """返回 None 表示通过，否则返回失败原因。"""
    text = "\n".join(case["lines"])
    info = parse_product_page(text)
    exp = case["expect"]

    price = info.get("price")
    original = info.get("original")
    saved = info.get("saved")

    if exp["price"] is None:
        # 现价被认坏的场景：不允许「凭空给一个看起来正确的价格」
        if price is not None and abs(price - exp["original"]) > 0.01:
            # 给出任何值都可能是错的，但至少要报警
            if not info.get("suspicious"):
                return f"现价认坏了却给出 {price} 且没报警"
        if not info.get("suspicious"):
            return "现价认坏了但没有任何 warning"
        return None

    # 现价必须精确
    if price is None:
        return "没认出价格"
    if abs(price - exp["price"]) > 0.01:
        return f"现价错：得到 {price}，应为 {exp['price']}"

    # 原价/优惠额：只要三者自洽即可（允许算术推导）
    if original is not None and saved is not None:
        if abs((price + saved) - original) > 0.05:
            return f"三者不自洽：{price}+{saved}≠{original}"
    elif original is not None:
        if original <= price:
            return f"原价 {original} 不大于现价 {price}"
    elif saved is not None:
        if saved <= 0:
            return f"优惠额 {saved} 不合理"

    return None


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    rng = random.Random(20261020)

    fails = []
    kinds = {}
    notes = {}

    for i in range(n):
        case = make_case(rng)
        kinds[case["kind"]] = kinds.get(case["kind"], 0) + 1
        if case["note"]:
            notes[case["note"]] = notes.get(case["note"], 0) + 1
        err = check(case)
        if err:
            fails.append((i, case, err))

    print()
    print(f"  跑了 {n} 例")
    print("  版式分布：" + "  ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    if notes:
        print("  扰动分布：" + "  ".join(f"{k}={v}" for k, v in sorted(notes.items())))
    print()

    if not fails:
        print(f"  ✓ 全部 {n} 例通过")
        print()
        return 0

    print(f"  ✗ {len(fails)} 例失败（{len(fails) / n * 100:.1f}%）")
    print()
    # 按错误类型归类，只打印前 8 类各 3 个样本
    by_reason: dict[str, list] = {}
    for idx, case, err in fails:
        key = err.split("：")[0].split("，")[0][:30]
        by_reason.setdefault(key, []).append((idx, case, err))

    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1]))[:8]:
        print(f"  ── {reason}（{len(items)} 例）")
        for idx, case, err in items[:3]:
            print(f"     #{idx} {case['kind']} {err}")
            for line in case["lines"][:6]:
                print(f"         {line}")
        print()
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
