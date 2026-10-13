"""
数据源注册表。

每个数据源都是一个函数：
    fetch(source_config: dict) -> FetchResult

想加新源，只要在 config.json 的 sources 里加一条，不用改代码。
"""

from __future__ import annotations

from ..models import FetchResult
from .aggregator import fetch_aggregator
from .http_json import fetch_http_json
from .mcd import fetch_mcd
from .meituan_official import fetch_meituan_official
from .union_api import fetch_union_api

# type 字段 -> 处理函数
_REGISTRY = {
    "aggregator": fetch_aggregator,
    "meituan_official": fetch_meituan_official,
    "http_json": fetch_http_json,
    "union_api": fetch_union_api,
    "mcd_mcp": fetch_mcd,
}


def fetch_all(sources: list[dict], only: str | None = None) -> FetchResult:
    """跑一遍所有启用的数据源。

    only: 只跑指定的源。支持逗号分隔的多个 id，例如
          only="free_aggregator,trip_coupons,movie_coupons,parcel_coupons"
          （线上定时任务需要这个——它只跑不需要注册的那几个源，
            不能把要 Token 的源也带上，否则页面底部会多出一堆"还没填 key"的提示。）
    单个源失败不会中断整体——把错误收集起来，其他源照常工作。
    """
    result = FetchResult()
    ran = 0

    # 把 "a,b,c" 拆成 {"a","b","c"}；没给就表示不筛选
    wanted: set[str] | None = None
    if only:
        wanted = {s.strip() for s in str(only).split(",") if s.strip()}

    for cfg in sources:
        sid = cfg.get("id", "unnamed")
        if wanted is not None and sid not in wanted:
            continue
        if not cfg.get("enabled", True):
            continue

        kind = cfg.get("type", "")
        handler = _REGISTRY.get(kind)
        label = cfg.get("label", sid)

        if handler is None:
            result.errors.append(f"[{label}] 未知的数据源类型：{kind}")
            continue

        ran += 1
        try:
            part = handler(cfg)
            result.extend(part)
        except Exception as e:  # 兜底：任何异常都只影响这一个源
            result.errors.append(f"[{label}] 抓取失败：{e}")

    if ran == 0:
        if wanted is not None:
            result.errors.append(
                f"指定的数据源一个都没跑到：{[s for s in wanted]}。"
                "检查 config.json 里这些 id 是否存在、enabled 是否为 true。"
            )
        else:
            result.notes.append("没有任何数据源被运行，请检查 config.json 里的 enabled 字段。")

    return result
