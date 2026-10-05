"""
数据源三：通用 JSON 接口（给愿意自己折腾的人用的扩展位）

作用：让你不用改代码，就能把「淘宝联盟 / 大淘客 / 好单库」这些接口接进来。
这些平台都需要你自己去注册拿 appkey，属于正规的推广联盟，注册免费。

用法：在 config.json 里加一条 type 为 http_json 的源，填 url / params / field_map。

举例（大淘客的商品券接口，字段名以官方文档为准，这里只是示意）：

{
  "id": "my_dtk",
  "type": "http_json",
  "enabled": true,
  "label": "我的大淘客",
  "platform": "淘宝闪购",
  "url": "https://openapi.dataoke.com/api/goods/get-goods-list",
  "method": "GET",
  "params": {"appKey": "你的key", "version": "v1.2.4", "pageSize": "50"},
  "list_path": "data.list",
  "field_map": {
    "title": "title",
    "code": "couponId",
    "url": "couponLink",
    "value": "couponPrice",
    "threshold": "couponMinPrice"
  }
}
"""

from __future__ import annotations

from ..http import HttpError, get_json, post_json
from ..models import Coupon, FetchResult


def _dig(obj, path: str):
    """按 "data.list" 这种点分路径往下取值。取不到返回 None。"""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_http_json(cfg: dict) -> FetchResult:
    label = cfg.get("label", cfg.get("id", "自定义源"))
    result = FetchResult()

    url = cfg.get("url")
    if not url:
        result.errors.append(f"[{label}] 没配 url")
        return result

    platform = cfg.get("platform", "其他")
    method = (cfg.get("method") or "GET").upper()
    params = cfg.get("params") or {}
    headers = cfg.get("headers") or {}
    body = cfg.get("json_body")
    timeout = cfg.get("timeout", 20)

    try:
        if method == "POST":
            payload = body if body is not None else params
            data = post_json(url, payload, headers=headers, timeout=timeout)
        else:
            data = get_json(url, params=params, headers=headers, timeout=timeout)
    except HttpError as e:
        result.errors.append(f"[{label}] {e.message}")
        return result

    list_path = cfg.get("list_path", "")
    rows = _dig(data, list_path) if list_path else None
    if rows is None:
        # 没配路径就猜一下：找响应里第一个「元素是字典的列表」
        for v in data.values() if isinstance(data, dict) else []:
            if isinstance(v, list) and v and isinstance(v[0], dict):
                rows = v
                break

    if not isinstance(rows, list):
        result.errors.append(
            f"[{label}] 没找到券列表，请检查 list_path 配置。返回的顶层键："
            f"{list(rows.keys()) if isinstance(rows, dict) else list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
        )
        return result

    fmap = cfg.get("field_map") or {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get(fmap.get("title", "title"), "") or "").strip()
        code = str(row.get(fmap.get("code", "coupon_code"), "") or "").strip()
        if not title and not code:
            continue
        result.coupons.append(
            Coupon(
                platform=platform,
                title=title or "未命名券",
                code=code,
                url=str(row.get(fmap.get("url", "url"), "") or ""),
                guideline=str(row.get(fmap.get("guideline", ""), "") or ""),
                source=label,
                tag=cfg.get("tag", "自定义源"),
                value=_num(row.get(fmap.get("value", "value"))),
                threshold=_num(row.get(fmap.get("threshold", "threshold"))),
            )
        )

    if not result.coupons:
        result.notes.append(f"[{label}] 接口通了，但一条券都没解析出来")

    return result
