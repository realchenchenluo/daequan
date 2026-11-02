"""
算出「这一单最多能省多少」，并给出怎么领、怎么点。

数据从哪来，说实话
────────────────────────────────────────────
**通用券**（平台发的，谁都能领）：能自动抓。项目里已经接了几个券源，
拿到的是口令券/会场券，带券码或链接。这部分可自动。

**店家券**（只在那家店能用的满减、店铺券）：**抓不到**。
没有任何公开接口能查「某家店的满减规则」，GitHub 上的开源项目也都死在这上面
（内部接口现在返回 403 / 302）。它只印在那家店的页面上，而且要登录才看得到。

所以店家券只有两条来路，都是项目里已经有的：
  · 用内置浏览器读那家店的页面（页面文字里就写着「满30减5」）
  · 或者你把页面文字复制过来

这个模块不关心数据怎么来的，只负责：
  把「通用券 + 店家券」放进同一个结算模型里，算出最优组合，并告诉你怎么操作。

一条重要的安全规则
────────────────────────────────────────────
有些券标题是「最高抢66元」。那是**上限**，不是保底。把它当 66 元减下去，
45 元的单能被算成 0 元——这个 bug 在关注清单里真出过一次。
所以 `value_is_max=True` 的券**只展示、不参与计算**。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .delivery import DeliveryResult, Offer, compute
from .stacking import Coupon as StackCoupon

# 一条规则的面额上限。超过基本是解析错了（比如把「满1000减1000」这种周年庆口号读进来）
_MAX_VALUE = 999.0
# 最多收多少条店铺优惠，防止页面上几十条小字把结果淹没
_MAX_PROMOS = 12


@dataclass
class Promo:
    """从页面文字里读出来的一条店铺优惠。"""

    text: str
    kind: str            # 满减 / 无门槛 / 折扣
    threshold: float = 0.0
    value: float = 0.0   # 满减/无门槛是元；折扣是 0.9 这种

    def describe(self) -> str:
        if self.kind == "满减":
            return f"满{self.threshold:g}减{self.value:g}"
        if self.kind == "无门槛":
            return f"无门槛减{self.value:g}"
        if self.kind == "折扣":
            return f"{(1 - self.value) * 10:.1f}折" if self.value < 1 else "折扣"
        return self.text

    def to_coupon(self, group: str = "店铺券") -> StackCoupon:
        if self.kind == "折扣":
            return StackCoupon(
                name=self.describe(), kind="折扣",
                threshold=self.threshold, value=self.value,
                exclusive_group=group, note=self.text,
            )
        if self.kind == "无门槛" or self.threshold <= 0:
            return StackCoupon(
                name=self.describe(), kind="无门槛", threshold=0, value=self.value,
                exclusive_group=group, note=self.text,
            )
        return StackCoupon(
            name=self.describe(), kind="满减",
            threshold=self.threshold, value=self.value,
            exclusive_group=group, note=self.text,
        )


# ── 从文字里认店铺优惠 ──────────────────────────────────

_RE_FULL = re.compile(
    r"满\s*(\d{1,4}(?:\.\d{1,2})?)\s*元?\s*减\s*(\d{1,4}(?:\.\d{1,2})?)"
)
_RE_NOTHING_1 = re.compile(
    r"(\d{1,4}(?:\.\d{1,2})?)\s*元\s*无门槛"
)
_RE_NOTHING_2 = re.compile(
    r"无门槛\s*(?:券|减|立减)?\s*(\d{1,4}(?:\.\d{1,2})?)\s*元"
)
_RE_INSTANT = re.compile(
    r"立减\s*(\d{1,4}(?:\.\d{1,2})?)\s*元"
)
_RE_DISCOUNT = re.compile(
    r"(?<!\d)(\d(?:\.\d)?)\s*折(?!扣)"
)


def _ok(value: float, threshold: float) -> bool:
    if value <= 0 or value > _MAX_VALUE:
        return False
    # 满 5 减 10 是可能存在的（首单/新客），但满 5 减 100 基本是解析错
    if threshold > 0 and value > threshold * 3:
        return False
    return True


def parse_store_promos(text: str) -> list[Promo]:
    """从店铺页文字里把满减/无门槛/折扣挑出来。

    只认形态非常固定的写法（满X减Y、N元无门槛、N折）。
    「特惠」「限时」这种没有数字的推广语一律忽略——宁可少报，也不瞎猜一个折扣。
    """
    raw = text or ""
    out: list[Promo] = []
    seen: set[tuple] = set()

    def add(p: Promo) -> None:
        key = (p.kind, round(p.threshold, 2), round(p.value, 2))
        if key in seen:
            return
        seen.add(key)
        out.append(p)

    for m in _RE_FULL.finditer(raw):
        thr, val = float(m.group(1)), float(m.group(2))
        if _ok(val, thr):
            add(Promo(m.group(0), "满减", thr, val))

    for pat in (_RE_NOTHING_1, _RE_NOTHING_2):
        for m in pat.finditer(raw):
            val = float(m.group(1))
            if _ok(val, 0):
                add(Promo(m.group(0), "无门槛", 0.0, val))

    for m in _RE_INSTANT.finditer(raw):
        val = float(m.group(1))
        if _ok(val, 0):
            add(Promo(m.group(0), "无门槛", 0.0, val))

    for m in _RE_DISCOUNT.finditer(raw):
        try:
            n = float(m.group(1))
        except ValueError:
            continue
        # 0.5~9.5 折才有意义；1折是 0.1，10折是原价（无意义）
        if not (0.5 <= n <= 9.5):
            continue
        rate = round(n / 10, 3)
        add(Promo(m.group(0), "折扣", 0.0, rate))

    return out[:_MAX_PROMOS]


# ── 折扣规划 ────────────────────────────────────────────

def promos_from_dicts(items) -> list[Promo]:
    """把 JSON 里带过来的字段还原成 Promo。

    浏览器桥在 state 里存的、网页回传的都是这种 dict，这里统一转换，
    免得每个调用点各写一遍 try/except。
    """
    out: list[Promo] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        try:
            kind = str(raw.get("kind") or "满减")
            if kind not in ("满减", "无门槛", "折扣"):
                continue
            thr = float(raw.get("threshold") or 0)
            val = float(raw.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if val <= 0 or val > _MAX_VALUE:
            continue
        out.append(
            Promo(
                text=str(raw.get("text") or raw.get("describe") or ""),
                kind=kind,
                threshold=max(0.0, thr),
                value=val,
            )
        )
    return out[:_MAX_PROMOS]


@dataclass
class Plan:
    """一单的「最多省多少 + 怎么办」。"""

    platform: str = ""
    items: float = 0.0
    delivery: float = 0.0
    packing: float = 0.0
    member: bool = False

    store_promos: list[Promo] = field(default_factory=list)
    # 能直接参与计算的通用券（有明确门槛和面额）
    usable_universal: list = field(default_factory=list)
    # 只能展示、不能参与计算的（「最高抢66元」这类，面额是上限不是保底）
    display_only: list = field(default_factory=list)

    result: DeliveryResult | None = None
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    top_up: list[dict] = field(default_factory=list)

    @property
    def max_discount(self) -> float:
        if self.result is None:
            return 0.0
        saved_food = self.result.food_saved
        saved_delivery = round(self.delivery - self.result.delivery, 2)
        return round(max(0.0, saved_food) + max(0.0, saved_delivery), 2)

    @property
    def final_price(self) -> float:
        return self.result.final_price if self.result else 0.0


def _universal_to_stack(c) -> StackCoupon | None:
    """把券源给的对象转成结算引擎的券。面额不明确的返回 None（宁可不参与算）。"""
    value = getattr(c, "value", None)
    if value is None or value <= 0:
        return None
    if getattr(c, "value_is_max", False):
        # 上限不是保底，不参与计算
        return None
    thr = getattr(c, "threshold", None) or 0.0
    if thr < 0:
        return None
    name = getattr(c, "title", "") or "平台券"
    note = getattr(c, "guideline", "") or ""
    if thr > 0:
        return StackCoupon(name=name, kind="满减", threshold=float(thr),
                           value=float(value), exclusive_group="平台券", note=note)
    return StackCoupon(name=name, kind="无门槛", threshold=0.0,
                       value=float(value), exclusive_group="平台券", note=note)


def build_plan(
    platform: str,
    items: float,
    delivery: float = 0.0,
    packing: float = 0.0,
    store_promos: list[Promo] | None = None,
    universal: list | None = None,
    member: bool = False,
) -> Plan:
    """算出这单的最优组合和操作步骤。

    items 是**菜品小计（优惠前）**。这个必须是原价小计，不是折后价——
    外卖平台的券门槛按原价小计判，用折后价会少用掉一张券。
    """
    plan = Plan(
        platform=platform or "未知平台",
        items=round(float(items or 0), 2),
        delivery=round(float(delivery or 0), 2),
        packing=round(float(packing or 0), 2),
        member=bool(member),
        store_promos=list(store_promos or []),
    )

    shop_coupons = [p.to_coupon("店铺券") for p in plan.store_promos]

    plat_coupons = []
    for c in (universal or []):
        if getattr(c, "platform", "") and platform and getattr(c, "platform") != platform:
            continue
        sc = _universal_to_stack(c)
        if sc is None:
            if getattr(c, "value_is_max", False) or getattr(c, "value", None) is None:
                plan.display_only.append(c)
            continue
        plat_coupons.append(sc)
        plan.usable_universal.append(c)

    if plan.items <= 0:
        plan.warnings.append("菜品合计是 0，没法算。先从菜单抓取那一页带过来，或者手填。")
        return plan

    offer = Offer(
        platform=plan.platform,
        items=plan.items,
        delivery=plan.delivery,
        packing=plan.packing,
        shop_discounts=shop_coupons,
        coupons=plat_coupons,
        member=plan.member,
        member_delivery_free=False,
    )
    plan.result = compute(offer)

    # ── 凑单建议：差一点就能用的券，比现在这张更划算才提 ──
    cur_saved = plan.result.food_saved
    for sc in shop_coupons + plat_coupons:
        if sc.kind != "满减":
            continue
        gap = round(sc.threshold - plan.items, 2)
        if gap <= 0:
            continue
        gain = round(sc.value - cur_saved, 2)
        if gain > 0:
            plan.top_up.append({
                "name": sc.name,
                "gap": gap,
                "value": sc.value,
                "gain": gain,
                "note": sc.note or "",
            })
    plan.top_up.sort(key=lambda x: (-x["gain"], x["gap"]))
    plan.top_up = plan.top_up[:3]

    # ── 操作步骤 ──
    steps: list[str] = []

    if plan.store_promos:
        names = "、".join(p.describe() for p in plan.store_promos[:4])
        steps.append(
            f"进店铺页，确认店铺优惠：{names}。"
            "有些店的满减要手动点「领取」，不点不生效。"
        )
    else:
        steps.append(
            "进店铺页，先看有没有「满减 / 店铺券」——本页没读到，"
            "可能是这店没有，也可能是抓的时候没停在优惠那一屏。"
        )

    if plan.usable_universal:
        parts = []
        for c in plan.usable_universal[:4]:
            code = getattr(c, "code", "") or ""
            url = getattr(c, "url", "") or ""
            title = getattr(c, "title", "") or ""
            if code:
                parts.append(f"「{title}」复制口令 {code} 去 App 打开")
            elif url:
                parts.append(f"「{title}」打开 {url}")
            else:
                parts.append(f"「{title}」在 App 里搜这个活动名")
        steps.append("领平台券：" + "；".join(parts) + "。")
    else:
        steps.append(
            "平台券：这次没找到面额明确的券。券源给的多半是「最高抢 X 元」，"
            "那是上限不是保底，我不把它算进金额里（算进去会让你以为能省很多）。"
        )

    steps.append(
        f"把商品凑到优惠后小计（这里按原价小计 {plan.items:g} 元判门槛），"
        f"结算页核对实付应该约 {plan.final_price:.2f} 元。"
    )
    steps.append(
        "如果结算页实付比这个数高，说明有券没叠上或门槛没到——"
        "按结算页实际显示的下单，别按这个数字下单。"
    )
    plan.steps = steps

    # ── 必须说清楚的风险 ──
    plan.warnings.append(
        "各平台「店铺满减、平台券、会员券、红包」能不能叠、按什么顺序减，"
        "都没有公开权威规则。这里按「店铺满减 → 平台券，门槛按原价小计」估算。"
    )
    if plan.display_only:
        plan.warnings.append(
            f"另有 {len(plan.display_only)} 张券只在页面上列出来、没参与计算，"
            "因为它们的面额是「最高 X 元」（上限），不是保底。"
        )
    if plan.result and plan.result.unused:
        plan.warnings.append(
            "没用上的：" + "；".join(plan.result.unused[:3])
        )
    return plan


def plan_to_dict(plan: Plan) -> dict:
    """给网页用的结构。"""
    def coupon_brief(c) -> dict:
        return {
            "title": getattr(c, "title", "") or "",
            "platform": getattr(c, "platform", "") or "",
            "code": getattr(c, "code", "") or "",
            "url": getattr(c, "url", "") or "",
            "guideline": getattr(c, "guideline", "") or "",
            "tag": getattr(c, "tag", "") or "",
            "threshold": getattr(c, "threshold", None),
            "value": getattr(c, "value", None),
            "value_is_max": bool(getattr(c, "value_is_max", False)),
            "discount_text": (c.discount_text() if hasattr(c, "discount_text") else ""),
        }

    return {
        "platform": plan.platform,
        "items": plan.items,
        "delivery": plan.delivery,
        "packing": plan.packing,
        "member": plan.member,
        "store_promos": [
            {"text": p.text, "kind": p.kind, "describe": p.describe(),
             "threshold": p.threshold, "value": p.value}
            for p in plan.store_promos
        ],
        "usable_universal": [coupon_brief(c) for c in plan.usable_universal],
        "display_only": [coupon_brief(c) for c in plan.display_only],
        "max_discount": plan.max_discount,
        "final_price": plan.final_price,
        "food_after": plan.result.food_after if plan.result else None,
        "steps": plan.steps,
        "warnings": plan.warnings,
        "top_up": plan.top_up,
    }
