"""
外卖到手价计算 —— 同一家店，在美团 / 淘宝闪购(饿了么) / 京东外卖 哪个真的更便宜。

为什么需要单独一个模块
────────────────────────────────────────────
外卖的到手价结构和买商品**不一样**：

    买商品：  标价 − 各种券
    点外卖：  菜品小计 + 配送费 + 打包费 − 门店满减 − 平台券 − 会员券 − 红包

多了配送费和打包费，而且**只看菜品价经常选错平台**：
A 平台菜便宜 5 块，但配送费贵 4 块、券还少 3 块，其实是 B 平台划算。
这个模块就是把这几项摊开来算清楚。

必须说清楚的前提
────────────────────────────────────────────
**我抓不到各平台的菜品价格。** 实测过：美团、饿了么、京东外卖的页面都是
纯 JS 渲染的应用外壳，返回的 HTML 里没有任何菜单或价格数据，而且都要登录。
所以：

  · 菜品价、配送费、打包费 —— **由你照着 App 里的结账页填进来**
  · 门店满减、你手里的券 —— 也由你填（我们的券源只给口令，不给面额）
  · 本模块负责：**把这些数字按外卖的真实计费方式算成到手价，并排序**

跟 stacking.py 的关系
────────────────────────────────────────────
券的计算复用 stacking.py 那套（含「顺序影响结果」的处理），
本模块只负责加上外卖特有的费用结构。

关于门槛基数的假设
────────────────────────────────────────────
外卖各平台的满减门槛按什么算、券之间怎么叠，**没有公开的权威规则**
（不像京东自营和拼多多有可查的文档）。这里统一按最常见的做法处理：

    门店满减 → 平台券 → 会员券 → 红包，门槛一律按「菜品小计」判定

这是个**假设**，不是查证过的事实。所以每个结果都会提醒以下单页为准。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .stacking import Coupon, best

# 外卖各平台（把券源里的平台名接上）
DELIVERY_PLATFORMS = ["美团", "淘宝闪购", "京东"]


@dataclass
class Offer:
    """一个平台上的这一单。数字都从你 App 的结账页抄。"""

    platform: str
    items: float = 0.0          # 菜品小计（没算优惠前的）
    delivery: float = 0.0       # 配送费
    packing: float = 0.0        # 打包费
    shop_discounts: list[Coupon] = field(default_factory=list)   # 门店满减
    coupons: list[Coupon] = field(default_factory=list)          # 平台券
    red_packet: float = 0.0     # 红包（直接减）
    member: bool = False        # 有会员吗（美团会员 / 饿了么超级会员）
    member_delivery_free: bool = False   # 会员是否免配送费
    member_coupon: Coupon | None = None  # 会员专属券/红包

    def all_coupons(self) -> list[Coupon]:
        cs = list(self.shop_discounts) + list(self.coupons)
        if self.member_coupon:
            cs.append(self.member_coupon)
        if self.red_packet > 0:
            cs.append(Coupon("红包", "无门槛", 0, self.red_packet, "红包"))
        return cs


@dataclass
class DeliveryResult:
    """一个平台算完的结果。"""

    platform: str
    items: float = 0.0
    food_after: float = 0.0     # 菜品部分优惠后的钱
    delivery: float = 0.0       # 实付配送费
    packing: float = 0.0
    steps: list = field(default_factory=list)
    unused: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def final_price(self) -> float:
        return round(self.food_after + self.delivery + self.packing, 2)

    @property
    def food_saved(self) -> float:
        return round(self.items - self.food_after, 2)


def compute(offer: Offer) -> DeliveryResult:
    """算这个平台的实际到手价。

    顺序：先把菜品部分的优惠算完（复用 stacking 引擎），
          再加上配送费和打包费——这两项一般不打折。
    """
    res = DeliveryResult(platform=offer.platform, items=round(offer.items, 2),
                         packing=round(offer.packing, 2))

    # 会员免配送费
    if offer.member and offer.member_delivery_free:
        res.delivery = 0.0
        res.notes.append("会员免配送费，配送费按 0 算")
    else:
        res.delivery = round(offer.delivery, 2)

    coupons = offer.all_coupons()
    if not coupons:
        res.food_after = round(offer.items, 2)
        if offer.delivery or offer.packing:
            res.notes.append("没有任何券/满减")
        return res

    # 门店满减和平台券在 stacking 里是两个不同类别，可以叠加
    # 注意：这里拿到的是 stacking.Result，它的价格字段叫 final_price，
    # 不是本模块 DeliveryResult 的 food_after。两者别搞混。
    # threshold_base="base"：外卖的平台券门槛通常按「商品原价小计」判，
    # 而不是按店铺满减减完之后的价格。写死用默认值会算错，
    # 实测：淘宝闪购 45 元单，满45减4 会因为没有 base 而判成不可用。
    r = best(offer.items, coupons, platform="外卖",
             has={"plus"} if offer.member else set(), threshold_base="base")
    res.food_after = max(round(r.final_price, 2), 0.0)
    res.steps = r.steps
    res.unused = r.unused

    return res


def compare(offers: list[Offer]) -> list[DeliveryResult]:
    """算一组，按到手价从低到高排。"""
    results = [compute(o) for o in offers]
    results.sort(key=lambda r: r.final_price)
    return results


# ────────────────────────────────────────────────
# 从粘贴的分享文本里认店名
# ────────────────────────────────────────────────

# 分享文案里的套话。要整段整段地去，否则「复制这条信息」只去掉「复制」，
# 会剩下「这条信息」被当成店名（实测踩到过）。
_NOISE_WORDS = (
    "复制这条信息", "复制此信息", "复制链接", "复制", "打开美团", "打开饿了么",
    "打开京东", "查看更多", "点击链接", "点此", "分享", "领取", "下单", "立即",
    "这条信息", "打开", "美团外卖", "饿了么", "京东外卖", "美团", "京东",
)

# 各平台分享出来的文本大概长这样：
#   美团：  【肯德基(中关村店)】https://xxxx
#   饿了么：肯德基(中关村店) - 饿了么 https://xxxx
#   京东： 【肯德基(中关村店)】京东外卖 https://xxxx
_NAME_PATTERNS = [
    re.compile(r"[【\[]([^】\]]{2,40})[】\]]"),          # 中文书名号/方括号里
    re.compile(r"^\s*([^\-–—\n]{2,40})\s*[-–—]\s*(?:饿了么|美团|京东)"),  # 「店名 - 饿了么」
    re.compile(r"([\u4e00-\u9fa5A-Za-z0-9()（）·\-]{2,40}?)\s*[-–—]\s*饿了么"),
]


def parse_share_text(text: str) -> tuple[str, str]:
    """从粘贴的分享文本里抽 (店名, 链接)。抽不到就给空串。

    为什么做得这么保守：外卖 App 的分享文案各家各版本都不一样，
    与其硬猜一个错的店名，不如抽不到就让用户自己填。

    判定规则（按顺序）：
      1. 命中「分享文案」的特征格式（【店名】、店名 - 饿了么 这种）→ 用里面的店名
      2. 有链接 → 把链接和常见干扰词去掉，剩下的短文本当店名
      3. 以上都不满足 → 返回空，交给调用方去问用户

    第 3 条是有意为之：早先版本「剩下什么都当店名」，结果用户随手粘一句
    普通的话也会被当成店名显示。宁可空着让他填，也别显示一个假店名。
    """
    text = (text or "").strip()
    url = ""
    m = re.search(r"https?://[^\s，,、）)]+", text)
    if m:
        url = m.group(0)

    # 1) 特征格式
    for pat in _NAME_PATTERNS:
        mm = pat.search(text)
        if mm:
            name = mm.group(1).strip()
            if name and not name.startswith("http"):
                return name, url

    # 2) 有链接时，把链接和干扰词去掉，剩下的短文本当店名。
    #    干扰词要覆盖整段话，不能只去掉「复制」而留下「这条信息」。
    if url:
        leftover = re.sub(r"https?://\S+", " ", text)
        leftover = re.sub(r"[【】\[\]]", " ", leftover)
        for kw in _NOISE_WORDS:
            leftover = leftover.replace(kw, " ")
        leftover = re.sub(r"\s+", " ", leftover).strip(" -–—·:：")
        if 2 <= len(leftover) <= 40:
            return leftover, url

    # 3) 认不出来就说认不出来
    return "", url


def render_comparison(results: list[DeliveryResult], shop: str = "") -> str:
    """把对比结果排成人能看的。"""
    out: list[str] = []
    title = f"{shop} · " if shop else ""
    out.append("  " + "═" * 58)
    out.append(f"  {title}外卖到手价对比")
    out.append("  " + "═" * 58)
    out.append("")
    out.append("    排名  平台          菜品优惠后   配送   打包    到手价")
    out.append("    " + "─" * 56)

    for i, r in enumerate(results, 1):
        mark = "  ←最便宜" if i == 1 else ""
        out.append(
            f"     {i}    {r.platform:<11} {r.food_after:>9.2f} {r.delivery:>7.2f}"
            f" {r.packing:>6.2f}  {r.final_price:>8.2f}{mark}"
        )

    if len(results) >= 2:
        gap = results[-1].final_price - results[0].final_price
        out.append("")
        if gap > 0.01:
            out.append(f"    最便宜的比最贵的省 {gap:.2f} 元"
                       f"（{gap / results[-1].final_price * 100:.1f}%）")
        else:
            out.append("    几个平台到手价一样。")

        # 只看菜品价会选错的提醒——这是本工具存在的意义
        cheapest_food = min(results, key=lambda r: r.food_after)
        if cheapest_food.platform != results[0].platform:
            out.append("")
            out.append(f"    ⚠️ 注意：**菜品最便宜的是 {cheapest_food.platform}**，"
                       f"但算上配送费、打包费和券之后，"
                       f"{results[0].platform} 才是真的划算。")
            out.append("       只看菜品价容易选错平台。")

    out.append("")
    out.append("  " + "─" * 58)
    for r in results:
        out.append("")
        out.append(f"  【{r.platform}】")
        out.append(f"    菜品 {r.items:.2f} → 优惠后 {r.food_after:.2f}"
                   f"（省 {r.food_saved:.2f}）")
        for s in r.steps:
            out.append(f"      · {s.coupon_name:<16} {s.before:>8.2f} → {s.after:>8.2f}")
        if r.delivery:
            out.append(f"      + 配送费 {r.delivery:.2f}")
        if r.packing:
            out.append(f"      + 打包费 {r.packing:.2f}")
        for u in r.unused:
            out.append(f"      × 没用上 {u}")
        for n in r.notes:
            out.append(f"      ℹ️ {n}")

    out.append("")
    out.append("  ⚠️ 满减门槛、券的叠加方式各平台没有公开权威规则，本工具统一按")
    out.append("     「门店满减 → 平台券 → 会员券 → 红包，门槛按菜品小计」估算。")
    out.append("     **以下单页结算时显示的为准。**")
    return "\n".join(out)
