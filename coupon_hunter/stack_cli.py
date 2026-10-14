"""
叠券 / 比价的命令行交互。

单独放一个文件是因为 cli.py 已经太长了，而这块逻辑自成一体：
解析用户输入的券 → 调 stacking 引擎 → 排版输出。
"""

from __future__ import annotations

from .stacking import PLATFORM_RULES, Coupon, Result, best, suggest_topup

# 平台名的小写别名 -> PLATFORM_RULES 里的正式名
PLATFORM_ALIASES = {
    "京东": "京东自营", "jd": "京东自营", "京东自营": "京东自营",
    "拼多多": "拼多多", "pdd": "拼多多", "多多": "拼多多",
    "淘宝": "淘宝/天猫", "天猫": "淘宝/天猫", "淘宝/天猫": "淘宝/天猫", "taobao": "淘宝/天猫",
    "通用": "通用", "": "通用",
}

GROUP_BY_KIND = {
    "满减": "平台券",
    "折扣": "折扣券",
    "无门槛": "红包",
    "补贴": "国补",
    "会员": "会员满减",
}


class SpecError(Exception):
    """券的写法看不懂时抛出，message 直接给用户看。"""


def parse_coupon(spec: str) -> Coupon:
    """把 "满减,300,50" 这样的写法解析成一张券。

    支持的写法（逗号分隔）：
        满减,300,50          满 300 减 50（平台券组）
        满减,300,50,店铺券    指定互斥组
        折扣,0.9             9 折券（value 是「付多少比例」）
        无门槛,20            直接减 20（红包组）
        补贴,0.15            按 15% 补贴（国补组）
        会员,500,30          会员满减，需要 plus 资质
    """
    parts = [p.strip() for p in str(spec).split(",") if p.strip() != ""]
    if not parts:
        raise SpecError("券是空的")

    kind = parts[0]
    if kind not in GROUP_BY_KIND:
        raise SpecError(
            f"不认识的券类型「{kind}」。可用：{'、'.join(GROUP_BY_KIND)}"
        )

    def num(i, default=None):
        if i >= len(parts):
            if default is None:
                raise SpecError(f"「{spec}」少了一个数字")
            return default
        try:
            return float(parts[i])
        except ValueError as e:
            raise SpecError(f"「{parts[i]}」不是数字") from e

    if kind in ("满减", "会员"):
        threshold, value = num(1), num(2)
        group = parts[3] if len(parts) > 3 else GROUP_BY_KIND[kind]
        name = f"{'会员' if kind=='会员' else ''}满{threshold:g}减{value:g}"
        return Coupon(name, kind, threshold, value, group,
                      requires="plus" if kind == "会员" else "")

    if kind == "折扣":
        rate = num(1)
        if rate <= 0:
            raise SpecError("折扣率要大于 0（0.9 表示 9 折）")
        if rate >= 1:
            raise SpecError("折扣率要小于 1（0.9 表示 9 折，1 表示不打折）")
        group = parts[2] if len(parts) > 2 else GROUP_BY_KIND[kind]
        zhe = round(rate * 10, 1)
        return Coupon(f"{zhe:g}折券", kind, 0, rate, group)

    if kind == "补贴":
        pct = num(1)
        group = parts[2] if len(parts) > 2 else GROUP_BY_KIND[kind]
        return Coupon(f"补贴{pct*100:g}%", kind, 0, pct, group)

    # 无门槛
    value = num(1)
    group = parts[2] if len(parts) > 2 else GROUP_BY_KIND[kind]
    return Coupon(f"减{value:g}元券", kind, 0, value, group)


def resolve_platform(name: str) -> str:
    key = (name or "").strip().lower()
    if key in PLATFORM_ALIASES:
        return PLATFORM_ALIASES[key]
    for alias, full in PLATFORM_ALIASES.items():
        if alias and alias in key:
            return full
    return "通用"


def render_result(res: Result, title: str = "") -> str:
    """把计算结果排成人能看的表格。"""
    out: list[str] = []
    if title:
        out.append(f"  【{title}】")

    out.append(f"    标价 {res.start_price:.2f}  →  实付 {res.final_price:.2f}"
               f"   （省 {res.total_saved:.2f}，{res.rate}%）")

    if res.steps:
        out.append("")
        out.append("    计算过程：")
        for s in res.steps:
            out.append(f"      · {s.coupon_name:<18} {s.before:>9.2f} → {s.after:>9.2f}"
                       f"   省 {s.saved:.2f}")

    if res.unused:
        out.append("")
        out.append("    没用上的：")
        for u in res.unused:
            out.append(f"      × {u}")

    if res.order_matters:
        out.append("")
        out.append(f"    ⚠️ 顺序可调的话最低能到 {res.optimized_price:.2f}"
                   f"（再省 {res.final_price - res.optimized_price:.2f}）")

    if res.notes:
        out.append("")
        for n in res.notes:
            out.append(f"    ℹ️ {n}")

    order = PLATFORM_RULES.get(res.platform, {}).get("order", [])
    out.append("")
    out.append(f"    规则依据：{res.platform} 顺序 = {' → '.join(order)}")
    out.append(f"    来源：{PLATFORM_RULES.get(res.platform, {}).get('sources', '无')}")
    out.append(f"    置信度：{res.confidence}")
    out.append("    ⚠️ 平台规则会变，**以下单页结算时显示的为准**。")
    return "\n".join(out)


def render_topup(tips: list[str]) -> str:
    if not tips:
        return ""
    out = ["", "    凑单建议："]
    out.extend(f"      · {t}" for t in tips)
    return "\n".join(out)


def parse_coupon_list(specs: list[str]) -> list[Coupon]:
    """解析一串券的写法，出错时抛 SpecError。"""
    return [parse_coupon(s) for s in specs if s and s.strip()]


__all__ = [
    "SpecError",
    "parse_coupon",
    "parse_coupon_list",
    "render_result",
    "render_topup",
    "resolve_platform",
    "best",
    "suggest_topup",
]
