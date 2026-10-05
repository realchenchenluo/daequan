"""
数据源四：电商联盟聚合平台（淘宝 / 天猫 / 抖音）

为什么需要这一层
────────────────────────────────────────────────
美团那边运气好，有官方开放的 AI 发券接口，不用注册就能用。
但**淘宝和抖音没有这种口子**：

  · 淘宝联盟（阿里妈妈）的转链、订单等 API 权限，现在个人开发者已经申请不到了
    —— 这是我们从折淘客官方 SDK 的 README 里读到的原话：
    「阿里妈妈已经无法申请到转链、订单等API权限，但可以用第三方接口使用到这些权限」
  · 抖音的电商/团购接口要对公资质，个人更拿不到

所以现实做法是走**聚合平台**：它们自己有联盟资质，把接口转出来给小开发者用。
注册免费，拿到 appkey 就能调。本模块就是对接它们。

支持两个平台，各自覆盖不同场景：

  ┌────────────┬──────────────────┬────────────────────────────────┐
  │ 平台       │ 能干什么         │ 说明                           │
  ├────────────┼──────────────────┼────────────────────────────────┤
  │ 大淘客     │ 淘宝/天猫 商品券  │ 商品列表接口直接带券面额，     │
  │ dataoke    │ **能浏览大额券**  │ 这是找淘宝大额券最合适的入口   │
  ├────────────┼──────────────────┼────────────────────────────────┤
  │ 折淘客     │ 抖音 商品搜索     │ 抖音侧有商品搜索和活动列表，   │
  │ zhetaoke   │ 抖音 活动列表     │ 能找到正在推的券             │
  └────────────┴──────────────────┴────────────────────────────────┘

⚠️ 一个必须说清楚的事实：**这两个平台我都无法替你测试到底能不能出券**，
因为需要 appkey。我验证到的是：接口真实存在、URL 和参数名正确、
错误处理正常（用假 key 能拿到清晰的鉴权错误）。

字段解析做了容错：不同平台、不同版本的字段名不一样，所以每个逻辑字段都配了
多个候选名，取第一个存在的。这样接口小改版不至于直接崩掉。
"""

from __future__ import annotations

from ..http import HttpError, get_json
from ..models import Coupon, FetchResult

# ──────────────────────────────────────────────────────────
# 平台配置
# ──────────────────────────────────────────────────────────

PROFILES: dict[str, dict] = {
    "dataoke": {
        "label": "大淘客",
        "platform": "淘宝",
        "url": "https://openapi.dataoke.com/api/goods/get-goods-list",
        # 大淘客用 appKey，参数名是驼峰
        "auth_key": "appKey",
        "extra_params": {"version": "v1.2.4", "pageId": "1", "pageSize": "100", "sort": "1"},
        "list_path": "data.list",
        "register_url": "https://www.dataoke.com",
        "help": "去 https://www.dataoke.com 注册（免费），在「开放平台」里拿到 appKey。",
    },
    "zhetaoke_douyin": {
        "label": "折淘客·抖音",
        "platform": "抖音",
        "url": "https://api.zhetaoke.com:10001/api/open_douyin_product_search.ashx",
        # 折淘客用 appkey（全小写）+ sid（淘客账号授权编号）
        "auth_key": "appkey",
        "need_sid": True,
        "extra_params": {"page": "1", "page_size": "50"},
        "list_path": "",  # 让它自动找列表
        "register_url": "https://www.zhetaoke.com",
        "help": (
            "去 https://www.zhetaoke.com 注册（免费）拿 appkey，"
            "再按它文档做一次「淘客账号授权」拿到 sid，两个都填上。"
        ),
    },
}

# ──────────────────────────────────────────────────────────
# 字段容错取值
# ──────────────────────────────────────────────────────────

_TITLE_KEYS = ("title", "dtitle", "goods_title", "product_title", "name", "goodsName")
# 注意：这里**不放 couponLink**。couponLink 是个网址，属于 _URL_KEYS。
# 早期版本把它也塞进来当口令，结果页面上同一个地址会显示两遍。
_CODE_KEYS = ("couponLinkTaoToken", "taoToken", "tao_token", "coupon_command",
              "dy_password", "dy_zlink", "password", "kouling", "tkl")
_URL_KEYS = ("couponLink", "coupon_link", "itemLink", "item_link", "detail_url", "url")
_VALUE_KEYS = ("couponPrice", "coupon_price", "couponAmount", "coupon_amount",
               "discount", "discountAmount")
_THRESHOLD_KEYS = ("couponMinPrice", "coupon_min_price", "couponConditions",
                   "coupon_conditions", "priceLimit", "startFee")
_END_KEYS = ("couponEndTime", "coupon_end_time", "endTime", "end_time", "expire_time")
_SALES_KEYS = ("monthSales", "month_sales", "sales", "sale_num", "soldNum")
_SHOP_KEYS = ("shopName", "shop_name", "sellerName", "brandName", "brand_name")


def _pick(obj: dict, keys: tuple[str, ...]):
    """按顺序取第一个存在且非空的字段。"""
    for k in keys:
        if k in obj:
            v = obj[k]
            if v not in (None, "", 0, "0"):
                return v
    return None


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


# 「满99减10」「满99元减10元」这类描述
_FULL_REDUCE = __import__("re").compile(
    r"满\s*(\d+(?:\.\d+)?)\s*元?\s*减\s*(\d+(?:\.\d+)?)"
)


def _parse_condition(text) -> tuple[float | None, float | None]:
    """把「满99减10」这种条件文本拆成 (门槛, 面额)。拆不出来返回 (None, None)。"""
    if not text:
        return None, None
    m = _FULL_REDUCE.search(str(text))
    if m:
        return float(m.group(1)), float(m.group(2))
    # 只有「满99」没有减多少
    m2 = __import__("re").search(r"满\s*(\d+(?:\.\d+)?)", str(text))
    if m2:
        return float(m2.group(1)), None
    return None, None


def _clean(text) -> str:
    """清掉标题里的 HTML 标签和多余空白。

    大淘客这类接口的标题常带高亮标记，比如
    「<span class=key>连衣裙</span>女 2026新款」，直接显示会很难看。
    """
    if text is None:
        return ""
    s = __import__("re").sub(r"<[^>]{0,80}>", "", str(text))
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return " ".join(s.split())


def _dig(obj, path: str):
    """按 "data.list" 点分路径取值。path 为空时自动找第一个「元素是字典的列表」。"""
    if not path:
        return _find_list(obj)

    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur if isinstance(cur, list) else _find_list(cur)


def _find_list(obj):
    """递归找响应里第一个「元素是字典的列表」，最多往下钻 3 层。"""
    if isinstance(obj, list):
        if not obj or isinstance(obj[0], dict):
            return obj
        return None
    if isinstance(obj, dict):
        for v in obj.values():
            found = _find_list(v)
            if found is not None:
                return found
    return None


# ──────────────────────────────────────────────────────────
# 错误识别：这几家把错误码藏在各种奇怪的地方
# ──────────────────────────────────────────────────────────

def _check_error(data, label: str, register_url: str, extra_hint: str = "") -> str | None:
    """返回人话错误信息；没问题返回 None。"""
    if not isinstance(data, dict):
        return None

    # 先把所有可能的「文案」收集起来，鉴权错误优先识别——
    # 这几家的报错字段各不相同，不先统一看一遍很容易漏。
    texts = " ".join(
        str(data.get(k, "")) for k in ("msg", "message", "content", "sub_msg", "error")
    ).lower()

    looks_like_auth = "appkey" in texts or "app_key" in texts or "鉴权" in texts

    # 折淘客：HTTP 200 但 body 里带 status != 200
    if "status" in data and data.get("status") not in (200, "200", None):
        if looks_like_auth:
            return f"[{label}] appkey 不对或没填。{extra_hint}"
        msg = str(data.get("content") or data.get("message") or "").strip()
        return f"[{label}] 接口返回错误（status={data.get('status')}）：{msg}"

    # 大淘客：正常是 {"code":0}；鉴权失败时 body 只有 {"message":"appkey不存在.."}
    if "code" in data and data.get("code") not in (0, 200, "0", "200", None):
        if looks_like_auth:
            return f"[{label}] appkey 不对或没填。{extra_hint}"
        msg = str(data.get("msg") or data.get("message") or "").strip()
        return f"[{label}] 接口返回错误（code={data.get('code')}）：{msg}"

    # 没有 code 字段，但仍然可能是错误响应
    if looks_like_auth:
        return f"[{label}] appkey 不对或没填。{extra_hint}"
    if "message" in data and "data" not in data and "list" not in data:
        return f"[{label}] 接口报错：{data.get('message')}"

    return None


# ──────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────

def fetch_union_api(cfg: dict) -> FetchResult:
    result = FetchResult()

    profile_name = cfg.get("profile", "")
    profile = PROFILES.get(profile_name)
    if profile is None:
        result.errors.append(
            f"[{cfg.get('label', cfg.get('id', '?'))}] 未知的 profile：{profile_name}。"
            f"可选：{'、'.join(PROFILES)}"
        )
        return result

    label = cfg.get("label") or profile["label"]
    appkey = (cfg.get("appkey") or "").strip()
    register_url = profile["register_url"]
    help_text = profile["help"]

    if not appkey:
        result.notes.append(f"[{label}] 还没填 appkey，已跳过。{help_text}")
        return result

    if profile.get("need_sid") and not (cfg.get("sid") or "").strip():
        result.notes.append(
            f"[{label}] 还没填 sid（淘客账号授权编号），已跳过。{help_text}"
        )
        return result

    # 组装请求参数
    params = {profile["auth_key"]: appkey}
    params.update(profile.get("extra_params", {}))
    if profile.get("need_sid"):
        params["sid"] = cfg["sid"].strip()

    # 用户可以在配置里覆盖参数（比如换关键词、换分页、加筛选条件）
    params.update(cfg.get("params") or {})

    keyword = (cfg.get("keyword") or "").strip()
    if keyword:
        for k in ("keyword", "q", "key", "kw"):
            params.setdefault(k, keyword)

    try:
        data = get_json(
            cfg.get("url") or profile["url"],
            params=params,
            timeout=cfg.get("timeout", 25),
        )
    except HttpError as e:
        # 大淘客鉴权失败会返回 HTTP 439，http 层会抛错，这里把它翻成人话
        body = (e.body or "").strip()
        if "appkey" in body.lower() or e.status in (401, 403, 439):
            result.errors.append(f"[{label}] appkey 不对或没填。{help_text}")
        else:
            result.errors.append(f"[{label}] {e.message} {body[:120]}".strip())
        return result

    err = _check_error(data, label, register_url, help_text)
    if err:
        result.errors.append(err)
        return result

    rows = _dig(data, cfg.get("list_path") or profile.get("list_path", ""))
    if not isinstance(rows, list):
        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        result.errors.append(f"[{label}] 没找到券列表。响应的顶层结构：{keys}")
        return result

    for row in rows:
        if not isinstance(row, dict):
            continue

        title = _clean(_pick(row, _TITLE_KEYS))
        if not title:
            continue

        code = _pick(row, _CODE_KEYS)
        url = _pick(row, _URL_KEYS)
        sales = _num(_pick(row, _SALES_KEYS))
        shop = _pick(row, _SHOP_KEYS)

        # 券门槛/面额：优先用结构化字段
        value = _num(_pick(row, _VALUE_KEYS))
        threshold = _num(_pick(row, _THRESHOLD_KEYS))

        # 结构化字段拿不到就啃文本，例如 couponConditions = "满99减10"
        cond = row.get("couponConditions") or row.get("coupon_conditions") or ""
        if cond:
            c_thr, c_val = _parse_condition(cond)
            if threshold is None:
                threshold = c_thr
            if value is None:
                value = c_val

        bits = []
        if shop:
            bits.append(str(shop))
        if sales:
            bits.append(f"月销{int(sales)}")
        guideline = " · ".join(bits) if bits else "复制口令或打开链接领取"
        if value:
            guideline += "｜券后价请以商品页为准"

        result.coupons.append(
            Coupon(
                platform=cfg.get("platform") or profile["platform"],
                title=title,
                code=str(code).strip() if code else "",
                url=str(url).strip() if url else "",
                guideline=guideline,
                source=label,
                tag=cfg.get("tag", "联盟券"),
                value=value,
                threshold=threshold,
                valid_to=str(_pick(row, _END_KEYS) or "")[:10],
            )
        )

    if not result.coupons:
        result.notes.append(f"[{label}] 接口通了但一条都没解析出来，可能字段变了或该分类暂时没券")

    return result
