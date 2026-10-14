"""
优惠叠加计算引擎 —— 算「叠完所有券之后到底付多少钱」。

为什么需要它
────────────────────────────────────────────
下单页一堆券，搞不清三件事：谁先用、谁跟谁互斥、差多少能用更大的券。
更麻烦的是**顺序会影响结果**：

    商品 100 元，手里有一张「8 折券」和一张「满 100 减 20」
      先 8 折 → 80 元，此时不满 100，满减用不了        → 付 80
      先满减   → 80 元，再 8 折 → 64 元                → 付 64
    **同一个用户、同样的券，顺序不同差 16 块。**

所以这个模块做三件事：
  1. 按各平台的**真实叠加顺序**逐张应用（每张都重新判门槛，因为前一张会改变价格）
  2. 处理**互斥**（同类券只能用一张）
  3. 穷举所有合法顺序，找出**最便宜**的那条（这是唯一能确定最优的办法）

规则来源与时效
────────────────────────────────────────────
平台叠加顺序和互斥规则来自开源项目 `agentsope/smartbuy-skill`（MIT 协议）的
`references/coupon-rules-jd.md` 和 `coupon-rules-pdd.md`，文档标注时点为
2026-05-29、有效期 6 个月。**这类规则平台会改**，所以：

  · 所有规则都集中在下面的 PLATFORM_RULES 里，改起来只改一处
  · 每条规则都带 sources 字段，写明依据
  · 算出来的结果都带「以你下单页结算时为准」的提示

「最优排序」这个思路来自 `CyrilFeng/Q-calculator`（965 星，Apache-2.0）——
它把优惠分成「平行式」（互不依赖）和「渐进式」（后一个取决于前一个的结果），
对渐进式的必须穷举顺序才能求最优。

不做什么
────────────────────────────────────────────
  · **不编造券**。你没告诉我有的券，我不会假设它存在。
  · **不猜平台政策**。不确定的一律走保守路径并明确标注。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

# 穷举顺序时的上限。7 的阶乘是 5040，再大就不值得算了
# （Q-calculator 也是缓存 7 以内的排列数，这个量级是业界共识）
MAX_PERMUTE = 7


# ──────────────────────────────────────────────────────────
# 优惠券模型
# ──────────────────────────────────────────────────────────

@dataclass
class Coupon:
    """一张券 / 一项优惠。

    kind 的含义：
      满减   —— 满 threshold 减 value（最常见）
      折扣   —— 打 value 折（value=0.9 表示 9 折），threshold 通常为 0
      无门槛 —— 直接减 value（threshold 为 0）
      补贴   —— 按比例补，如国补 15%（value=0.15），基数是「减完其他优惠后的价」
      会员   —— 会员满减（满 threshold 减 value），且门槛按「减完立减后」判定
    """

    name: str
    kind: str
    threshold: float = 0.0
    value: float = 0.0
    # 互斥组：同一组里最多只能用一张（比如「平台券」组只能用最大的那张）
    exclusive_group: str = ""
    # 需要的资质，比如 "plus"（京东 Plus 会员）；用户不具备就会跳过
    requires: str = ""
    note: str = ""

    def usable_at(self, price: float, has: set[str]) -> bool:
        if self.requires and self.requires not in has:
            return False
        if self.kind in ("满减", "会员"):
            return price >= self.threshold
        return price > 0

    def apply(self, price: float) -> float:
        """把这张券作用到价格上，返回减后的价格。

        每种优惠的基数不一样，这是最容易算错的地方：
          · 满减/无门槛：直接减
          · 折扣：按当前价打折
          · 补贴：按当前价的比例补（不是按原价！）
        """
        if self.kind == "折扣":
            return round(price * self.value, 2)
        if self.kind == "补贴":
            return round(price * (1 - self.value), 2)
        return round(price - self.value, 2)

    def saving_at(self, price: float, has: set[str]) -> float:
        if not self.usable_at(price, has):
            return 0.0
        return round(price - self.apply(price), 2)


# ──────────────────────────────────────────────────────────
# 平台规则
# ──────────────────────────────────────────────────────────

# order 里的每一项是「优惠类别」，按平台规定的先后顺序排。
# 同一类别内可以有多张券，用 exclusive_group 决定能不能同时用。
PLATFORM_RULES: dict[str, dict] = {
    "京东自营": {
        "order": ["平台券", "品类券", "折扣券", "会员满减", "国补"],
        "desc": "平台满减 → 品类券 → 折扣券 → Plus 满减 → 国补（云闪付支付时）",
        "sources": "agentsope/smartbuy-skill · coupon-rules-jd.md（MIT，时点 2026-05）",
        "notes": [
            "国补 15% 的基数是「减完所有非补贴优惠之后」的价，不是标价。",
            "Plus 满减的门槛按「减完所有立减之后」判定。",
            "国补按省份/品类有资质限制，本工具不替你判断资格。",
        ],
    },
    "拼多多": {
        "order": ["百亿补贴", "平台券", "红包", "秒杀"],
        "desc": "百亿补贴价 → 减平台券 → 减红包 → 限时秒杀（如适用）",
        "sources": "agentsope/smartbuy-skill · coupon-rules-pdd.md（MIT，时点 2026-05）",
        "notes": [
            "百亿补贴价就是商品现价，不是原价减出来的。",
            "拼多多没有京东那种 Plus 阶梯满减，也没有跨店满减。",
            "百亿补贴和国补是两回事，绝大多数百亿补贴商品不享国补。",
            "同类平台券只能用一张（系统自动选大的）。",
        ],
    },
    "淘宝/天猫": {
        "order": ["店铺券", "平台券", "红包"],
        "desc": "店铺券 → 平台券 → 红包（平台未公布完整规则，此为常见顺序）",
        "sources": "无权威来源，按常见做法排；smartbuy-skill 明确表示天猫只给"
                   "「大致估算 + 去下单页核对」",
        "confidence": "低",
        "notes": [
            "淘宝/天猫没有公开完整的叠加顺序，这个顺序是常见做法，未必准确。",
            "**务必以下单页结算时显示为准**，本结果只能当参考。",
        ],
    },
    "通用": {
        "order": ["店铺券", "平台券", "红包"],
        "desc": "店铺券 → 平台券 → 红包（无平台特定信息时的通用顺序）",
        "sources": "无，通用兜底",
        "confidence": "低",
        "notes": ["没有这个平台的确切规则，结果仅供参考。"],
    },
}


# ──────────────────────────────────────────────────────────
# 计算
# ──────────────────────────────────────────────────────────

@dataclass
class Step:
    """应用一张券的一步。"""

    coupon_name: str
    before: float
    after: float

    @property
    def saved(self) -> float:
        return round(self.before - self.after, 2)


@dataclass
class Result:
    """一次计算的结果。

    final_price 是**按平台规定顺序**算出来的，也就是你下单时实际会看到的价格。
    optimized_price 是穷举所有顺序后的理论最低价——只有平台允许你调整
    优惠使用顺序时才拿得到，**不能当成你一定能付到的价**。

    为什么要把两个分开：测试时发现，如果只报最优价，会把「国补挪到平台券
    前面」这种下单页根本做不到的顺序算进来，报出一个你拿不到的价格。
    报一个错的低价比报一个保守价糟糕得多。
    """

    start_price: float = 0.0
    final_price: float = 0.0
    optimized_price: float = 0.0
    steps: list[Step] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)   # 没用上的券，以及原因
    platform: str = "通用"
    order_desc: str = ""
    confidence: str = "中"
    notes: list[str] = field(default_factory=list)

    @property
    def total_saved(self) -> float:
        return round(self.start_price - self.final_price, 2)

    @property
    def rate(self) -> float:
        if self.start_price <= 0:
            return 0.0
        return round(self.total_saved / self.start_price * 100, 1)

    @property
    def order_matters(self) -> bool:
        """调整顺序能不能更便宜。"""
        return self.optimized_price < self.final_price - 0.001


def _apply_order(
    price: float,
    coupons: list[Coupon],
    has: set[str],
    order: list[str],
) -> Result:
    """按给定顺序把券依次作用到价格上。

    每一步都重新判门槛——因为前一张券会改变价格，后面那张可能因此
    变得可用或不可用。这正是「顺序影响结果」的根源，也是最容易算错的地方。
    """
    res = Result(start_price=round(price, 2))
    remaining = list(coupons)
    used_names: set[str] = set()

    # 用局部变量跟踪当前价，别用 res.final_price——
    # 它的初始值是 0，而被减到 0 也是合法结果，两者分不清。
    # （早先版本用 `if not res.final_price` 兜底，结果价格真的减到 0 时
    #   会被重置回原价，实测踩到过。）
    current = round(price, 2)

    for category in order:
        # 找出这一类别下现在可用的券
        candidates = [
            c for c in remaining
            if c.exclusive_group == category and c.name not in used_names and c.usable_at(current, has)
        ]
        if not candidates:
            continue
        # 同类互斥：只用省得最多的那张
        best_c = max(candidates, key=lambda c: c.saving_at(current, has))
        before = current
        after = max(best_c.apply(before), 0.0)   # 不可能付负数，兜到 0
        res.steps.append(Step(best_c.name, before, after))
        current = after
        used_names.add(best_c.name)

    res.final_price = round(current, 2)
    current_final = res.final_price

    # 没用上的券，逐张说明具体原因。别写「门槛没达到或同类有更划算的」
    # 这种含糊话——两种原因差别很大，要说清是哪一种。
    for c in remaining:
        if c.name in used_names:
            continue
        if c.requires and c.requires not in has:
            res.unused.append(f"{c.name}（需要「{c.requires}」资质，你没有）")
        elif c.kind in ("满减", "会员") and current_final < c.threshold:
            res.unused.append(
                f"{c.name}（要满 {c.threshold:g}，算到最后只有 {current_final:.2f}，差 "
                f"{c.threshold - current_final:.2f}）"
            )
        elif c.exclusive_group not in order:
            res.unused.append(f"{c.name}（这个平台的规则里没有「{c.exclusive_group}」这一类）")
        else:
            same = [x for x in remaining
                    if x.exclusive_group == c.exclusive_group and x.name in used_names]
            if same:
                res.unused.append(f"{c.name}（和「{same[0].name}」同类，只能选一张）")
            else:
                res.unused.append(f"{c.name}（没有生效的机会）")

    return res


def best(
    price: float,
    coupons: list[Coupon],
    platform: str = "通用",
    has: set[str] | None = None,
) -> Result:
    """算出下单时的实际到手价，另外给出「顺序可调时」的理论最低价。

    final_price  —— 按平台规定顺序算的，这才是你实际会付的
    optimized_price —— 穷举所有顺序后的理论最低，只在平台允许调整顺序时才拿得到

    ⚠️ 不要把 optimized_price 当成你能付到的价。实测过：如果只报最优价，
    会把「国补挪到平台券前面」这种下单页做不到的顺序算进来（国补是云闪付
    支付时才算的，不可能排在前面），结果报出一个拿不到的价。
    """
    has = has or set()
    rule = PLATFORM_RULES.get(platform) or PLATFORM_RULES["通用"]
    base_order = list(rule["order"])

    # 手里的券涉及的类别。**不在平台规则里的类别要追加进去**，
    # 否则那张券会被静默丢掉——用户明明有这张券，工具却当它不存在，
    # 报出偏高的价格。（测试时踩到过：自定义类别全被丢，算出原价。）
    present = {c.exclusive_group for c in coupons if c.exclusive_group}
    unknown = sorted(present - set(base_order))
    full_order = base_order + unknown

    baseline = _apply_order(price, coupons, has, full_order)

    # 平台规定顺序的结果作为主结果
    baseline.platform = platform
    baseline.order_desc = rule["desc"]
    baseline.confidence = rule.get("confidence", "中")
    baseline.notes = list(rule.get("notes", []))

    # 再穷举，看顺序能不能更便宜（仅作参考）
    effective = [c for c in full_order if c in present]
    optimized = baseline.final_price
    if 1 < len(effective) <= MAX_PERMUTE:
        results = [
            _apply_order(price, coupons, has, list(perm)) for perm in itertools.permutations(effective)
        ]
        optimized = min(r.final_price for r in results)

    baseline.optimized_price = round(optimized, 2)

    # 「顺序有讲究」不写进 notes——输出层已经有一条结构化的提示了，
    # 两边都写会重复显示。

    return baseline


def suggest_topup(
    price: float,
    coupons: list[Coupon],
    has: set[str] | None = None,
) -> list[str]:
    """凑单建议：再买多少能解锁更大额的券，值不值。

    只对「满减」类券给建议，因为折扣券和补贴券没有门槛概念。
    """
    has = has or set()
    tips: list[str] = []
    for c in coupons:
        if c.kind != "满减" or c.threshold <= price:
            continue
        gap = round(c.threshold - price, 2)
        # 多花 gap 能多省 value；只有「多省的 > 多花的」才值得凑
        if c.value > gap:
            tips.append(
                f"再买 {gap:.2f} 元可用「{c.name}」（满{c.threshold:.0f}减{c.value:.0f}），"
                f"净省 {c.value - gap:.2f} 元 —— 值得凑"
            )
        else:
            tips.append(
                f"再买 {gap:.2f} 元可用「{c.name}」，但只能多省 {c.value:.2f} 元，"
                f"倒亏 {gap - c.value:.2f} 元 —— 不划算"
            )
    return tips
