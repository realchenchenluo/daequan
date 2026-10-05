"""
数据源一：免费聚合口令接口（无需登录，开箱即用）

这个接口返回的是各大平台官方推出来的「口令」——本质是官方联盟的推广链接，
用户把口令复制到 App 里打开，就能领到券。券是真的，只是发券方是推广渠道。

它的价值：不需要登录、不需要手机号、不需要任何 key，装上就能用。
它的局限：券是「通用」的，不是给你账号定制的，力度通常不如官方直发。

返回结构长这样（键名可能变，所以代码是防御式解析）：
{
  "美团隐藏外卖券列表": [{"title": "...", "coupon_code": "...", "guideline": "..."}],
  "饿了么/淘宝闪购隐藏外卖券列表": [...],
  "京东隐藏外卖券列表": [...],
  "查找更多优惠券": {"coupon_h5_qrcode_img_url": "...", "guideline": "..."}
}
"""

from __future__ import annotations

from ..http import HttpError, get_json
from ..models import Coupon, FetchResult

DEFAULT_ENDPOINT = "https://agskills.moontai.top/coupon/takeout"

# 响应里的键名 -> 展示用的平台名。前缀匹配，容忍键名后面多几个字
_PLATFORM_HINTS = [
    ("美团", "美团"),
    ("饿了么", "淘宝闪购"),
    ("淘宝闪购", "淘宝闪购"),
    ("闪购", "淘宝闪购"),
    ("京东", "京东"),
]


def _guess_platform(key: str) -> str:
    for hint, name in _PLATFORM_HINTS:
        if hint in key:
            return name
    return key.replace("隐藏外卖券列表", "").strip() or "其他"


def fetch_aggregator(cfg: dict) -> FetchResult:
    endpoint = cfg.get("endpoint") or DEFAULT_ENDPOINT
    label = cfg.get("label", "免费聚合源")
    result = FetchResult()

    try:
        data = get_json(endpoint, timeout=cfg.get("timeout", 20))
    except HttpError as e:
        result.errors.append(f"[{label}] {e.message}")
        return result

    if not isinstance(data, dict):
        result.errors.append(f"[{label}] 返回格式不是字典，可能接口改版了")
        return result

    for key, value in data.items():
        # 情况一：值是一个列表 —— 这就是券列表
        if isinstance(value, list):
            platform = _guess_platform(key)
            for item in value:
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or "").strip()
                code = (item.get("coupon_code") or "").strip()
                if not title and not code:
                    continue
                result.coupons.append(
                    Coupon(
                        platform=platform,
                        title=title or "未命名券",
                        code=code,
                        guideline=(item.get("guideline") or "").strip(),
                        source=label,
                        tag="口令券",
                    )
                )

        # 情况二：值是一个对象且带二维码 —— 那是聚合领券页面
        elif isinstance(value, dict) and (
            "coupon_h5_qrcode_img_url" in value or "qrcode" in str(value.keys())
        ):
            img = value.get("coupon_h5_qrcode_img_url", "")
            result.coupons.append(
                Coupon(
                    platform="通用",
                    title=(value.get("title") or key).strip(),
                    url=img,
                    guideline=(value.get("guideline") or "").strip(),
                    source=label,
                    tag="扫码会场",
                )
            )

    if not result.coupons and not result.errors:
        result.notes.append(f"[{label}] 接口通了，但没解析出任何券，可能接口改版")

    return result
