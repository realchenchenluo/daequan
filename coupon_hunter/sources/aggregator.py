"""
数据源一：免费聚合口令接口（无需登录，开箱即用）

这个接口返回的是各大平台官方推出来的「口令」——本质是官方联盟的推广链接，
用户把口令复制到 App 里打开，就能领到券。券是真的，只是发券方是推广渠道。

它的价值：不需要登录、不需要手机号、不需要任何 key，装上就能用。
它的局限：券是「通用」的，不是给你账号定制的，力度通常不如官方直发。

同一个站有四个端点，返回结构**不一样**，这里都要能吃下：

  /coupon/takeout  外卖     → {"美团隐藏外卖券列表": [...], "京东...": [...]}  字典套列表
  /coupon/trip     出行     → [{"title":..., "coupon_url":...}, ...]          顶层数组
  /coupon/movie    电影票   → 同上
  /coupon/parcel   快递     → 同上

（我一开始只按第一种写，结果另外三个端点怎么都解析不出来。
  所以这里做了两种结构的兼容，改代码时注意别只测一个端点。）
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

# 顶层数组那种结构用这些字段名
_TITLE_KEYS = ("title", "name", "desc")
_URL_KEYS = ("coupon_url", "url", "link")
_CODE_KEYS = ("coupon_code", "code", "kouling")
_GUIDE_KEYS = ("guideline", "instruction", "desc")


def _guess_platform(key: str) -> str:
    for hint, name in _PLATFORM_HINTS:
        if hint in key:
            return name
    return key.replace("隐藏外卖券列表", "").strip() or "其他"


def _pick(obj: dict, keys: tuple[str, ...]):
    for k in keys:
        v = obj.get(k)
        if v not in (None, ""):
            return v
    return None


def _from_dict(data: dict, label: str, default_platform: str) -> FetchResult:
    """结构一：{平台名: [券...]}，外加一个含二维码的对象。"""
    result = FetchResult()

    for key, value in data.items():
        # 1a) 值是列表 —— 这就是券列表
        if isinstance(value, list):
            platform = _guess_platform(key) if key != "data" else default_platform
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

        # 1b) 值是对象且带二维码 —— 那是聚合领券页面
        elif isinstance(value, dict) and "coupon_h5_qrcode_img_url" in value:
            result.coupons.append(
                Coupon(
                    platform="通用",
                    title=(value.get("title") or key).strip(),
                    url=value.get("coupon_h5_qrcode_img_url", ""),
                    guideline=(value.get("guideline") or "").strip(),
                    source=label,
                    tag="扫码会场",
                )
            )

    return result


def _from_list(rows: list, label: str, default_platform: str) -> FetchResult:
    """结构二：顶层就是数组，元素是扁平对象。"""
    result = FetchResult()

    for item in rows:
        if not isinstance(item, dict):
            continue

        title = str(_pick(item, _TITLE_KEYS) or "").strip()
        if not title:
            continue

        code = str(_pick(item, _CODE_KEYS) or "").strip()
        url = str(_pick(item, _URL_KEYS) or "").strip()
        # 二维码图片地址也算一种「url」，但要和可点击链接区分开。
        # 两个字段名都认：coupon_qrcode_img_url 是单个券的码，
        # coupon_h5_qrcode_img_url 是「更多优惠券」那种聚合入口的码。
        qr = str(
            item.get("coupon_qrcode_img_url")
            or item.get("coupon_h5_qrcode_img_url")
            or ""
        ).strip()
        guide = str(_pick(item, _GUIDE_KEYS) or "").strip()

        # 既没有券码也没有链接也没有二维码的，是纯文字条目，跳过
        if not code and not url and not qr:
            continue

        result.coupons.append(
            Coupon(
                platform=default_platform,
                title=title,
                code=code,
                url=url or qr,
                guideline=guide,
                source=label,
                tag="领券入口" if (code or url) else "扫码会场",
            )
        )

    return result


def fetch_aggregator(cfg: dict) -> FetchResult:
    endpoint = cfg.get("endpoint") or DEFAULT_ENDPOINT
    label = cfg.get("label", "免费聚合源")
    platform = cfg.get("platform", "其他")

    try:
        data = get_json(endpoint, timeout=cfg.get("timeout", 20))
    except HttpError as e:
        r = FetchResult()
        r.errors.append(f"[{label}] {e.message}")
        return r

    # 两种结构各走各的解析；都不是就如实报错，不假装没券
    if isinstance(data, dict):
        result = _from_dict(data, label, platform)
    elif isinstance(data, list):
        result = _from_list(data, label, platform)
    else:
        r = FetchResult()
        r.errors.append(f"[{label}] 返回格式不认识（{type(data).__name__}），可能接口改版了")
        return r

    if not result.coupons and not result.errors:
        result.notes.append(f"[{label}] 接口通了，但没解析出任何券，可能接口改版")

    return result
