"""
给出「怎么下单最省」的操作步骤。

用户的需求很明确：**不代下单，只告诉我怎么操作**。
所以这里输出的是「你先点这个、再勾那个」的步骤清单。

为什么要给步骤而不只给数字
────────────────────────────────────────────
因为同样的券，**用不用得上取决于你怎么勾**：

  · 有些平台的券是系统自动选的，你没法挑
  · 有些要手动去「我的-优惠券」里先领
  · 有些会员券默认不勾，要自己点
  · 有些满减要「凑单」才够门槛

只告诉你「最终 39 元」没用，你还得自己摸索怎么点出来。
所以这里把「能省多少」和「怎么点出来」一起给。

诚实标注
────────────────────────────────────────────
各平台的具体交互（哪个按钮、默认勾不勾）**各家不一样、也会改版**。
所以步骤分成两类：
  · **确定能说的**：先领券、凑单够门槛、注意有效期——这些是通用逻辑
  · **可能要确认的**：具体在哪个位置勾选——会标注「位置以你 App 为准」

不编造具体的界面路径，因为编了也是错的。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .stacking import Coupon, Result


@dataclass
class Advice:
    """一个平台的操作建议。"""

    platform: str
    final_price: float = 0.0
    saved: float = 0.0
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    coupon_names: list[str] = field(default_factory=list)

    def render(self) -> str:
        out = [f"  【{self.platform}】到手约 {self.final_price:.2f}"
               f"（省 {self.saved:.2f}）"]
        if self.coupon_names:
            out.append(f"    要用到的券：{'、'.join(self.coupon_names)}")
        if self.steps:
            out.append("    操作步骤：")
            for i, s in enumerate(self.steps, 1):
                out.append(f"      {i}. {s}")
        if self.warnings:
            out.append("    注意：")
            for w in self.warnings:
                out.append(f"      ⚠️ {w}")
        return "\n".join(out)


def build_advice(
    platform: str,
    result: Result,
    coupons: list[Coupon],
    has_member: bool = False,
    target_gap: float | None = None,
) -> Advice:
    """根据计算结果，生成这个平台的操作步骤。

    result  —— stacking.best() 的结果
    coupons —— 你手里这个平台的券
    target_gap —— 如果凑单能解锁更大的券，这里给差值
    """
    adv = Advice(
        platform=platform,
        final_price=result.final_price,
        saved=result.total_saved,
        coupon_names=[s.coupon_name for s in result.steps],
    )

    used = {s.coupon_name for s in result.steps}

    # ① 先把没用上的券分两类：够不着的（可以凑单）和互斥的（只能选一个）
    need_claim = []
    need_topup = []
    for c in coupons:
        if c.name in used:
            continue
        if c.kind in ("满减", "会员") and c.threshold > result.start_price:
            gap = round(c.threshold - result.start_price, 2)
            # 只有「多省的 > 多花的」才值得凑
            if c.value > gap:
                need_topup.append((c, gap))
        elif c.requires and not has_member:
            adv.warnings.append(f"「{c.name}」需要会员，你目前没有，所以没算进去")

    # ② 通用步骤
    adv.steps.append("打开对应 App，把商品加到购物车，进结算页")

    if need_claim:
        adv.steps.append(
            f"先去「我的 → 优惠券」把这几张领了（没领的话结算页不会自动带）："
            f"{'、'.join(need_claim)}"
        )

    if result.steps:
        names = "、".join(s.coupon_name for s in result.steps)
        adv.steps.append(
            f"结算页确认这几张券**已经勾上**：{names}"
            f"（有的平台默认不勾，要手动点）"
        )

    if need_topup:
        for c, gap in sorted(need_topup, key=lambda x: -x[0].value):
            adv.steps.append(
                f"想用「{c.name}」的话，再凑 {gap:.2f} 元（净省 "
                f"{c.value - gap:.2f}）"
            )

    adv.steps.append("最后核对一下实付金额，和上面算的对不对得上")

    # ③ 提醒
    if result.order_matters:
        adv.warnings.append(
            f"这张单的顺序有讲究：如果 App 允许你调整优惠使用顺序，"
            f"最低能到 {result.optimized_price:.2f}；"
            f"但很多平台是系统自动排序的，改不了"
        )

    if result.confidence == "低":
        adv.warnings.append(
            "这个平台的叠加规则没有公开文档，我们是按常见做法估的，"
            "**以下单页显示的为准**"
        )

    adv.warnings.append("券有有效期，用之前看一眼别过期了")

    return adv


def render_comparison(advices: list[Advice]) -> str:
    """把多个平台的建议排在一起，最便宜的放最前面。"""
    out = []
    out.append("")
    out.append("  " + "═" * 60)
    out.append("  怎么下单最省")
    out.append("  " + "═" * 60)

    if not advices:
        out.append("")
        out.append("  没有可算的方案。")
        out.append("")
        return "\n".join(out)

    advices = sorted(advices, key=lambda a: a.final_price)

    if len(advices) > 1:
        gap = advices[-1].final_price - advices[0].final_price
        out.append("")
        if gap > 0.01:
            out.append(f"  建议走 **{advices[0].platform}**，比最贵的省 {gap:.2f} 元。")
        else:
            out.append("  几个平台差不多，挑你顺手的就行。")

    for a in advices:
        out.append("")
        out.append(a.render())

    out.append("")
    out.append("  " + "─" * 60)
    out.append("  ⚠️ 本工具只给建议，不会替你下单。券的最终可用性和金额")
    out.append("     以你下单页结算时显示的为准。")
    out.append("")
    return "\n".join(out)
