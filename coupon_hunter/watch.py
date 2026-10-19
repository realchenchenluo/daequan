"""
关注清单 + 自动比价 —— 让工具每天自己跑，你只在"该买"的时候被打扰。

为什么是这么设计的
────────────────────────────────────────────
用户要的是「全自动，不可能每天盯着看」。这里必须把一个区分讲清楚：

  · **自动化"监控和提醒"** —— 能做，而且是成熟做法（慢慢买、Keepa 都是这么干的）
  · **自动化"抓取平台价格"** —— 做不到：三个电商和三个外卖平台的页面
    都是 JS 渲染 + 登录墙，实测过（淘宝只返回 5KB 反爬页，拼多多直接要登录）
  · **自动化"下单和实时减免"** —— 做不到，也不该做：券的核销和金额减免发生在
    **平台的结算页**，那是平台自己的代码。第三方工具不在那个位置上，
    物理上无法介入。任何声称能"替你在平台结算时自动减免"的，要么是假的，
    要么是在替平台做结算（那就成了平台方）。

所以真正可行的"全自动"是：**你录一次基准价，之后它每天自己算、自己比、自己提醒。**
你不需要每天看，它在该买的时候告诉你。

工作方式
────────────────────────────────────────────
  1. 你把关注的商品/店铺录进来（名称 + 各平台价格 + 你手里的券）
  2. 定时任务每 2 小时跑一次，把**最新抓到的券**匹配到这些条目上
  3. 算出「今天用券后最便宜是多少」，和你的目标价比
  4. 命中就标记出来，页面上排在最前面

券是自动更新的（GitHub Actions 每 2 小时），价格是你录的基准价。
这个分工是诚实的：券会变，价格不会自己变——因为抓不到。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .store import data_dir


def watchlist_path() -> Path:
    return data_dir() / "watchlist.json"


@dataclass
class WatchItem:
    """一个关注的条目。"""

    name: str
    kind: str = "商品"          # 商品 / 外卖
    target: float | None = None  # 目标价：低于这个就提醒
    note: str = ""
    # 各平台的基准价：{"京东": 399, "拼多多": 359}
    prices: dict = field(default_factory=dict)
    # 各平台的券（写法同 stack_cli.parse_coupon）
    coupons: dict = field(default_factory=dict)   # {"京东": ["满减,300,50", "折扣,0.9"]}
    # 外卖专用：配送费、打包费
    fees: dict = field(default_factory=dict)      # {"美团": {"delivery": 3, "packing": 1}}
    added_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def load() -> list[WatchItem]:
    p = watchlist_path()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = []
    for row in raw if isinstance(raw, list) else []:
        if isinstance(row, dict) and row.get("name"):
            items.append(WatchItem(**{k: v for k, v in row.items()
                                      if k in WatchItem.__dataclass_fields__}))
    return items


def save(items: list[WatchItem]) -> None:
    p = watchlist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps([i.to_dict() for i in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add(item: WatchItem) -> None:
    items = load()
    item.added_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 同名的替换掉，避免重复
    items = [i for i in items if i.name != item.name]
    items.append(item)
    save(items)


def remove(name: str) -> bool:
    items = load()
    kept = [i for i in items if i.name != name]
    if len(kept) == len(items):
        return False
    save(kept)
    return True


def clear() -> None:
    save([])


# ──────────────────────────────────────────────────────────
# 自动检查
# ──────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    """一个条目的检查结果。"""

    name: str
    kind: str
    best_platform: str = ""
    best_price: float | None = None
    target: float | None = None
    hit: bool = False           # 是否达到目标价
    detail: list[str] = field(default_factory=list)
    available_coupons: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.best_price is None:
            return f"{self.name}：没有可比的价格"
        s = f"{self.name}：{self.best_platform} {self.best_price:.2f}"
        if self.target is not None:
            if self.hit:
                s += f"（达到目标价 {self.target:.2f}）"
            else:
                s += f"（目标 {self.target:.2f}，还差 {self.best_price - self.target:.2f}）"
        return s


def check_all(fetched_coupons=None) -> list[CheckResult]:
    """把所有关注项算一遍。

    fetched_coupons: 本次抓到的 Coupon 列表，用来把「平台券」匹配到条目上。
                     传 None 就只用条目里自己录的券。
    """
    from .stack_cli import SpecError, parse_coupon
    from .stacking import Coupon, best

    items = load()
    results: list[CheckResult] = []

    for item in items:
        r = CheckResult(name=item.name, kind=item.kind, target=item.target)

        if not item.prices:
            results.append(r)
            continue

        # 把抓到的券按平台归一下类，方便匹配
        by_platform: dict[str, list] = {}
        for c in fetched_coupons or []:
            by_platform.setdefault(c.platform, []).append(c)

        best_platform, best_price = "", None

        for platform, price in item.prices.items():
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue

            # 这个条目在这个平台上录的券
            specs = item.coupons.get(platform) or []
            coupons = []
            for spec in specs:
                try:
                    coupons.append(parse_coupon(spec))
                except SpecError:
                    pass

            # 外卖还要加上配送/打包费
            fee = item.fees.get(platform) or {}
            delivery = float(fee.get("delivery", 0) or 0)
            packing = float(fee.get("packing", 0) or 0)

            # 匹配抓到的平台券（标题里带这个平台名的）
            # ⚠️ 抓来的券**不能直接当钱用**。
            # 那些券只有标题，面额是从标题里猜的，而且往往是「最高抢66元」
            # 这种上限值，不是保底值。早先版本直接拿它当无门槛券减，
            # 结果 45 元的单被算成 0 元——错得离谱。
            #
            # 所以这里只把抓到的券当**参考信息**列出来，不参与金额计算。
            # 真正能算的券必须由用户在条目里明确录（面额是他自己确认过的）。
            matched_titles = []
            for src_name, cs in by_platform.items():
                if src_name == platform or src_name in platform or platform in src_name:
                    for c in cs:
                        matched_titles.append(c.title)

            r.available_coupons.extend(matched_titles)
            plat_kind = "外卖" if item.kind == "外卖" else "通用"
            res = best(price, coupons, plat_kind, threshold_base="base")
            total = res.final_price + delivery + packing

            r.detail.append(
                f"{platform}: {price:.2f} → {res.final_price:.2f}"
                + (f" + 配送{delivery:.0f} + 打包{packing:.0f}" if delivery or packing else "")
                + f" = {total:.2f}"
            )

            if best_price is None or total < best_price:
                best_platform, best_price = platform, total

        r.best_platform = best_platform
        r.best_price = round(best_price, 2) if best_price is not None else None
        if item.target is not None and r.best_price is not None:
            r.hit = r.best_price <= item.target

        results.append(r)

    # 命中的排前面，其次按价格从低到高
    results.sort(key=lambda x: (not x.hit, x.best_price if x.best_price is not None else 1e9))
    return results


def render_report(results: list[CheckResult]) -> str:
    """把检查结果排成文本。"""
    out = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out.append("")
    out.append("  " + "═" * 58)
    out.append(f"  关注清单检查 · {now}")
    out.append("  " + "═" * 58)

    if not results:
        out.append("")
        out.append("  清单是空的。先加一个：")
        out.append('    python run.py 关注 --名 "某款耳机" --价 "京东=399,拼多多=359" --目标 350')
        out.append("")
        return "\n".join(out)

    hits = [r for r in results if r.hit]
    out.append("")
    if hits:
        out.append(f"  🔔 有 {len(hits)} 个达到目标价：")
        for r in hits:
            out.append(f"    · {r.summary()}")
    else:
        out.append("  暂时没有达到目标价的，继续等。")

    out.append("")
    out.append("  " + "─" * 58)
    for r in results:
        mark = "🔔 " if r.hit else "   "
        out.append(f"{mark}{r.name}")
        if r.best_price is not None:
            out.append(f"     最便宜：{r.best_platform} {r.best_price:.2f}"
                       + (f"（目标 {r.target:.2f}）" if r.target is not None else ""))
        for d in r.detail:
            out.append(f"       {d}")
        if r.available_coupons:
            out.append(f"       可用券：{'、'.join(dict.fromkeys(r.available_coupons))[:80]}")

    out.append("")
    out.append("  ⚠️ 价格是你录的基准价，券是自动抓的。价格变动需要你手动更新。")
    out.append("     原因：三个电商和三个外卖平台的页面都是 JS 渲染 + 登录墙，")
    out.append("     实测过，抓不到（详见 调研结论.md 第十节）。")
    out.append("")
    return "\n".join(out)
