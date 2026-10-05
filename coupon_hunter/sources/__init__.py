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
from .meituan_official import fetch_meituan_official

# type 字段 -> 处理函数
_REGISTRY = {
    "aggregator": fetch_aggregator,
    "meituan_official": fetch_meituan_official,
    "http_json": fetch_http_json,
}


def fetch_all(sources: list[dict], only: str | None = None) -> FetchResult:
    """跑一遍所有启用的数据源。

    only: 只跑 id 匹配的某一个源（用于排查问题）。
    单个源失败不会中断整体——把错误收集起来，其他源照常工作。
    """
    result = FetchResult()
    ran = 0

    for cfg in sources:
        sid = cfg.get("id", "unnamed")
        if only and sid != only:
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
        result.notes.append("没有任何数据源被运行，请检查 config.json 里的 enabled 字段。")

    return result
