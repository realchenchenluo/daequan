"""
优惠力度打分。

为什么要打分：抓来的券只有一个标题，比如
  「美团外卖节(主推)🔥🔥」          面额未知
  「淘宝闪购-天天领红包(最高抢66元)」 最高 66 元
  「美团隐藏口令 852298 （大额）」    号称大额，但没写数字
用户要的是「大额券」，所以我得从文字里尽量把面额抠出来，抠不出来的就靠关键词给个大概分。

打分结果只用来排序——让大额的排前面，不是精确的金钱计算。
"""

from __future__ import annotations

import re

from .models import Coupon

# 「满30减15」「满30元减15元」这类写法
_RE_FULL_REDUCE = re.compile(r"满\s*(\d+(?:\.\d+)?)\s*元?\s*减\s*(\d+(?:\.\d+)?)\s*元?")
# 「减15元」「立减15」「省15元」
_RE_REDUCE = re.compile(r"(?:立减|减|省)\s*(\d+(?:\.\d+)?)\s*元?")
# 「最高抢66元」「最高66元」。带「最高/抢/领」前缀的说明这只是上限，不是保底，要标记出来
_RE_AMOUNT_MAX = re.compile(r"(?:最高|至高|封顶)\s*(?:抢|领|得|省)?\s*(\d+(?:\.\d+)?)\s*元")
_RE_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*元")
# 「9.9元购360元年卡」——这是花钱买券包，不是白得的券，要单独识别并从文本里剔除
_RE_BUY_PACK = re.compile(r"(\d+(?:\.\d+)?)\s*元\s*(?:购|买|抢购|开通|得)")

# 关键词加权：命中就加分。分值是我按经验拍的，只影响排序先后。
_KEYWORD_BONUS: list[tuple[str, float]] = [
    ("免单", 60),
    ("大额", 45),
    ("隐藏", 30),
    ("神券", 30),
    ("超级红包", 25),
    ("专属", 15),
    ("新人", 12),
    ("新客", 12),
    ("主推", 10),
    ("品牌", 8),
    ("品质", 8),
    ("叠", 8),        # 「叠红包」= 可以叠加，通常更划算
    ("全场景", 8),
    ("通用", 6),
    ("专享", 6),
    ("专场", 5),
    ("🔥", 5),
]

# 减分项：这些词说明券的限制多，或者根本不是白拿的
_KEYWORD_PENALTY: list[tuple[str, float]] = [
    ("年卡", -25),
    ("月卡", -20),
    ("会员", -15),
    ("9.9元购", -40),
    ("学生", -10),  # 有身份门槛
]


def parse_amounts(title: str) -> tuple[float | None, float | None, float | None, bool]:
    """从标题里抠出 (门槛, 面额, 买券包价格, 是否只是上限)。

    面额取值优先级：满减的「减」部分 > 「立减/省」 > 单独的「X 元」。
    """
    threshold: float | None = None
    value: float | None = None
    pack_price: float | None = None
    is_max = False

    # 先把「9.9元购360元年卡」整段抹掉。否则 9.9 会被当成折扣、360 会被当成面额，
    # 两种都是错的——这是在卖券包，不是发券。
    m = _RE_BUY_PACK.search(title)
    if m:
        pack_price = float(m.group(1))
        title = title[: m.start()] + " " + title[m.end():]

    m = _RE_FULL_REDUCE.search(title)
    if m:
        threshold = float(m.group(1))
        value = float(m.group(2))
    else:
        m = _RE_REDUCE.search(title)
        if m:
            value = float(m.group(1))
        else:
            m = _RE_AMOUNT_MAX.search(title)
            if m:
                value = float(m.group(1))
                is_max = True
            else:
                m = _RE_AMOUNT.search(title)
                if m:
                    value = float(m.group(1))

    # 兜底：像「9.9元购360元年卡」这样，抹掉「9.9元购」之后，剩下的 360 元是券包的
    # 总面值，不是一个能减 360 的券。面额比售价大好几倍明显不合理，清掉。
    if pack_price is not None and value is not None and value > pack_price * 3:
        value = None

    return threshold, value, pack_price, is_max


def score_coupon(coupon: Coupon) -> Coupon:
    """给单张券打分，直接写回 coupon.score / score_reason。"""
    threshold, value, pack_price, is_max = parse_amounts(coupon.title)

    # 如果数据源已经给了准确面额（比如美团官方接口），就用准确的，别去猜
    if coupon.threshold is not None:
        threshold = coupon.threshold
    if coupon.value is not None:
        value = coupon.value
        is_max = False

    coupon.threshold = threshold
    coupon.value = value
    coupon.value_is_max = is_max

    score = 0.0
    reasons: list[str] = []

    if value is not None:
        # 「最高抢66元」只是理论上限，实际到手往往少得多，所以按七折算
        score += value * (0.7 if is_max else 1.0)
        reasons.append(f"{'最高' if is_max else ''}面额{value:g}元")
    if threshold:
        # 同样的面额，门槛越低越划算
        score += max(0.0, 30.0 - threshold) * 0.5
    if pack_price is not None:
        score -= 30
        reasons.append(f"需花{pack_price:g}元购买")

    for kw, bonus in _KEYWORD_BONUS:
        if kw in coupon.title:
            score += bonus
    for kw, penalty in _KEYWORD_PENALTY:
        if kw in coupon.title:
            score += penalty

    coupon.score = round(score, 2)
    coupon.score_reason = "；".join(reasons) if reasons else "按关键词估算"
    return coupon


def rank(coupons: list[Coupon]) -> list[Coupon]:
    """打分并排序，大额券排前面。"""
    scored = [score_coupon(c) for c in coupons]
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored


def dedupe(coupons: list[Coupon]) -> list[Coupon]:
    """按平台+标题+券码去重，保留分数最高的那条。"""
    best: dict[str, Coupon] = {}
    for c in coupons:
        k = c.key()
        if k not in best or c.score > best[k].score:
            best[k] = c
    return list(best.values())
