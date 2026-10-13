"""
数据源五：麦当劳中国官方 MCP（麦麦省优惠券）

这是全项目里**唯一一个真正的官方开放接口**，比前面那些第三方聚合靠谱得多：
  · 提供方：麦当劳中国自己
  · 端点：https://mcp.mcd.cn
  · 官方文档：https://open.mcd.cn/mcp
  · 官方仓库：https://github.com/M-China/mcd-mcp-server
  · Token：免费，手机号登录就能拿
  · 限流：600 次/分钟

里面有 24 个工具，和券直接相关的：
  available-coupons      查可领取的麦麦省券   ← 我们主要用这个
  auto-bind-coupons      一键领取所有可领券   ← 有副作用，默认不开
  query-my-coupons       查账户卡包里的券
  campaign-calendar      活动日历

⚠️ 关于我没法验证的部分
────────────────────────────────────────────
这个源需要你的 Token，我没有，所以**我无法验证它到底能返回什么结构**。
我能确认的是：端点真实存在、协议握手正确、错误处理正常（实测假 Token 返回 401
并被翻译成人话）。工具返回的具体字段只能等你跑一次才知道。

所以解析写成「容错 + 兜底」：
  · 先从返回文本里抠 JSON，递归找券列表，按多个候选字段名提取
  · 实在解析不出来，就把原始文本当成一条「提示」显示出来，
    你至少能看到服务端到底返回了什么，而不是莫名其妙什么都没有
"""

from __future__ import annotations

import os

from ..mcp_client import McpClient, McpError, tool_result_json, tool_result_text
from ..models import Coupon, FetchResult

DEFAULT_URL = "https://mcp.mcd.cn"
REGISTER_URL = "https://open.mcd.cn/mcp"

# 券列表里可能出现的字段名，挨个试
_NAME_KEYS = ("couponName", "name", "title", "couponTitle", "displayName", "desc", "description")
_VALUE_KEYS = ("amount", "discount", "couponValue", "value", "faceValue", "denomination")
_THRESHOLD_KEYS = ("minAmount", "threshold", "priceLimit", "minPrice", "condition", "useCondition")
_END_KEYS = ("endTime", "expireTime", "validEnd", "expiryDate", "endDate", "validTo")
_CODE_KEYS = ("couponCode", "code", "id", "couponId")

HELP = (
    f"去 {REGISTER_URL} 用手机号登录 → 控制台 → 激活 → 复制 Token，"
    '填到 config.json 里 mcd_official 那条的 "token"（或设环境变量 MCD_MCP_TOKEN）。'
)


def _pick(obj: dict, keys: tuple[str, ...]):
    for k in keys:
        v = obj.get(k)
        if v not in (None, "", 0, "0"):
            return v
    return None


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        import re

        m = re.search(r"(\d+(?:\.\d+)?)", str(v))
        return float(m.group(1)) if m else None


def _find_coupon_list(node, depth: int = 0):
    """递归找「元素是字典且看起来像券」的列表。

    为什么这么写：我没法事先知道服务端把券放在哪一层
    （可能是 data.list、可能是 result.coupons、也可能直接就是顶层数组）。
    """
    if depth > 4:
        return None

    if isinstance(node, list):
        if not node:
            return None
        if isinstance(node[0], dict):
            # 至少有一个元素带「像券名」的字段才认
            for item in node[:5]:
                if isinstance(item, dict) and _pick(item, _NAME_KEYS):
                    return node
        return None

    if isinstance(node, dict):
        # 优先看名字里带 coupon / list / data 的键
        for key in sorted(node.keys(), key=lambda k: (0 if "coupon" in k.lower() else
                                                      1 if k.lower() in ("list", "data", "items", "result") else 2)):
            found = _find_coupon_list(node[key], depth + 1)
            if found is not None:
                return found
    return None


def fetch_mcd(cfg: dict) -> FetchResult:
    result = FetchResult()
    label = cfg.get("label", "麦当劳官方券")
    token = (cfg.get("token") or os.environ.get("MCD_MCP_TOKEN") or "").strip()

    if not token:
        result.notes.append(f"[{label}] 还没填 Token，已跳过。{HELP}")
        return result

    tool = cfg.get("tool", "available-coupons")
    client = McpClient(url=cfg.get("url") or DEFAULT_URL, token=token,
                       timeout=cfg.get("timeout", 25))

    try:
        client.initialize()
        raw_result = client.call_tool(tool, cfg.get("arguments") or {})
    except McpError as e:
        result.errors.append(f"[{label}] {e.message}")
        return result
    except Exception as e:  # 兜底，别让一个源把整个搜券带崩
        result.errors.append(f"[{label}] {type(e).__name__}: {e}")
        return result

    data = tool_result_json(raw_result)
    rows = _find_coupon_list(data) if data is not None else None

    if not rows:
        # 解析不出来时不假装没券——把服务端原话亮出来，让用户和我们都看得到
        text = tool_result_text(raw_result).strip()
        snippet = (text[:200] + "…") if len(text) > 200 else text
        if not snippet:
            result.notes.append(f"[{label}] 调用成功但没有任何内容返回")
        else:
            result.notes.append(
                f"[{label}] 拿到结果但结构没认出来，原文如下（可以把这段发给我修解析）：{snippet}"
            )
        return result

    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(_pick(row, _NAME_KEYS) or "").strip()
        if not name:
            continue

        value = _num(_pick(row, _VALUE_KEYS))
        threshold = _num(_pick(row, _THRESHOLD_KEYS))
        code = _pick(row, _CODE_KEYS)

        result.coupons.append(
            Coupon(
                platform=cfg.get("platform", "麦当劳"),
                title=name,
                code=str(code).strip() if code else "",
                url=str(_pick(row, ("link", "url", "jumpUrl")) or "").strip(),
                guideline="麦当劳官方券｜打开麦当劳 App 或小程序使用",
                source=label,
                tag="官方券",
                value=value,
                threshold=threshold,
                valid_to=str(_pick(row, _END_KEYS) or "")[:10],
            )
        )

    if not result.coupons:
        result.notes.append(f"[{label}] 当前没有可领取的券")

    return result
