"""
统一的数据模型。

不管券是从哪个渠道抓来的（美团官方接口、免费聚合接口、还是你自己配的淘宝联盟接口），
进来之后一律先转换成 Coupon 对象，后面的排序、打印、存网页就都只认这一个格式。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Coupon:
    """一张优惠券 / 一个领券入口。"""

    platform: str          # 平台：美团 / 淘宝闪购 / 京东 …
    title: str             # 券名，比如「美团外卖节」「淘宝闪购-叠红包」
    code: str = ""         # 口令 / 券码，用户复制到 App 里用
    guideline: str = ""    # 领取说明
    url: str = ""          # 直达链接（如果有）
    source: str = ""       # 这条数据是哪个数据源给的，方便排查
    tag: str = "口令券"     # 类型：口令券 / 官方直发 / 会场

    # 面额信息（能解析出来就填，解析不出来就是 None）
    threshold: float | None = None   # 门槛，满多少元可用
    value: float | None = None       # 面额，减多少元
    value_is_max: bool = False       # True 表示这只是上限（「最高抢66元」），不是保底
    valid_from: str = ""             # 生效日期
    valid_to: str = ""               # 失效日期

    # 排序得分，由 rank.py 计算
    score: float = 0.0
    score_reason: str = ""

    def key(self) -> str:
        """去重用的唯一标识：同平台同名同券码视为同一张券。"""
        return f"{self.platform}|{self.title}|{self.code}"

    def discount_text(self) -> str:
        """人话描述这张券的力度。"""
        if self.threshold and self.value:
            t = _fmt(self.threshold)
            v = _fmt(self.value)
            return f"满{t}减{v}"
        if self.value:
            prefix = "最高减" if self.value_is_max else "减"
            return f"{prefix}{_fmt(self.value)}元"
        return "力度未知"

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt(x: float) -> str:
    """12.0 -> '12'，12.5 -> '12.5'，避免出现难看的 12.0 元。"""
    return str(int(x)) if float(x) == int(x) else f"{x:g}"


@dataclass
class FetchResult:
    """一次抓取的汇总结果。"""

    coupons: list[Coupon] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)      # 哪个源失败了，为什么
    notes: list[str] = field(default_factory=list)       # 需要提醒用户注意的事

    def extend(self, other: "FetchResult") -> None:
        self.coupons.extend(other.coupons)
        self.errors.extend(other.errors)
        self.notes.extend(other.notes)
