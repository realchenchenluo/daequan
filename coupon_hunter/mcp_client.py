"""
MCP（Model Context Protocol）客户端 —— 只用标准库实现 Streamable HTTP 传输。

为什么需要它
────────────────────────────────────────────
麦当劳中国开放了官方的 MCP 服务（https://mcp.mcd.cn），里面有
`available-coupons`（查可领的麦麦省券）、`auto-bind-coupons`（一键领券）
这类工具。但 MCP 不是普通 REST 接口，它是一套 JSON-RPC 协议，
所以得按它的规矩来：先握手，再调工具。

协议要点（照着 MCP 规范和麦当劳官方接入指南实现）
────────────────────────────────────────────
  端点      https://mcp.mcd.cn
  传输      Streamable HTTP（一个 POST 端点搞定，不是 WebSocket）
  鉴权      Authorization: Bearer <token>
  握手      必须先 initialize，拿到可能存在的 Mcp-Session-Id
            再发一个 notifications/initialized 通知
  调用      POST tools/call，body 里带 {name, arguments}
  响应      可能是 application/json，也可能是 text/event-stream（SSE）

SSE 这点最容易踩坑：服务端有可能把结果包装成
    event: message
    data: {"jsonrpc":"2.0","id":1,"result":{...}}
这种形式返回。所以不能直接 json.loads 整个 body，得先把 data: 那行剥出来。
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"


class McpError(Exception):
    """MCP 调用失败。message 是给人看的中文说明。"""

    def __init__(self, message: str, code: int | None = None, raw: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code
        self.raw = raw


class McpClient:
    """一个极简的 MCP 客户端，够用就行。

    典型用法：
        c = McpClient(token=...)
        c.initialize()
        result = c.call_tool("available-coupons", {})
    """

    def __init__(self, url: str = DEFAULT_URL, token: str = "", timeout: float = 25.0):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 1
        self.server_info: dict = {}

    # ── 底层请求 ────────────────────────────────────────

    def _headers(self) -> dict:
        h = {
            "Content-Type": "application/json",
            # MCP 规范要求同时接受这两种，服务端二选一
            "Accept": "application/json, text/event-stream",
            "User-Agent": "CouponHunter/1.0",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    @staticmethod
    def _extract_json(body: str, content_type: str):
        """把响应体解析成对象。

        兼容两种情况：
          · application/json      → 直接 loads
          · text/event-stream     → 从 data: 行里捞 JSON（可能有多个，取最后一个）
        """
        if "text/event-stream" in (content_type or "").lower():
            payload = None
            for line in body.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    payload = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
            if payload is None:
                raise McpError("服务端返回了 SSE 但没有可解析的数据", raw=body[:300])
            return payload

        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise McpError(f"返回内容不是合法 JSON：{body[:200]}", raw=body[:300]) from e

    def _post(self, payload: dict, *, need_response: bool = True):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, headers=self._headers(), method="POST")

        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                # 会话 ID 只在 initialize 的响应里给一次，之后所有请求都要带上
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                body = resp.read().decode("utf-8", errors="replace")
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            # 实测：没带 Token 时麦当劳返回 403，Token 不对才返回 401，
            # 所以这两个都要当成鉴权问题处理，别让用户看到裸的 HTTP 码。
            if e.code in (401, 403):
                raise McpError(
                    "Token 无效、已过期或没填。去 https://open.mcd.cn/mcp "
                    "用手机号登录，进控制台点激活，复制 Token 填到 config.json。",
                    code=e.code,
                    raw=err_body,
                ) from e
            if e.code == 429:
                raise McpError("请求太频繁了（限流 600 次/分钟），等一下再试", code=429) from e
            raise McpError(f"服务器返回 HTTP {e.code}", code=e.code, raw=err_body[:300]) from e
        except urllib.error.URLError as e:
            raise McpError(f"网络连接失败：{e.reason}") from e
        except TimeoutError as e:
            raise McpError("请求超时") from e

        # 通知类请求（notifications/initialized）服务端可能返回 202 空体，不需要解析
        if not need_response or not body.strip():
            return None

        return self._extract_json(body, ctype)

    def _rpc(self, method: str, params: dict | None = None):
        """发一个带 id 的 JSON-RPC 请求并等响应。"""
        msg_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params

        resp = self._post(payload)
        if not isinstance(resp, dict):
            raise McpError(f"{method} 返回了预期外的内容", raw=str(resp)[:200])

        if "error" in resp:
            err = resp["error"] or {}
            raise McpError(
                f"{method} 出错：{err.get('message', err)}",
                code=err.get("code"),
            )
        return resp.get("result", {})

    # ── 协议动作 ────────────────────────────────────────

    def initialize(self) -> dict:
        """握手。必须先做这一步，否则后续调用会被拒。"""
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "coupon-hunter", "version": "1.0.0"},
            },
        )
        self.server_info = result.get("serverInfo", {}) or {}

        # 按规范补一个 initialized 通知（没有 id，不等响应）
        try:
            self._post(
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                need_response=False,
            )
        except McpError:
            # 有些服务端不强制这一步，失败不影响后续调用
            pass

        return result

    def list_tools(self) -> list[dict]:
        result = self._rpc("tools/list")
        return result.get("tools", []) or []

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """调用一个工具，返回原始的 result 对象。"""
        return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})


# ── 结果解析辅助 ────────────────────────────────────────

def tool_result_text(result: dict) -> str:
    """把 tools/call 的返回拼成一段文本。

    MCP 约定返回 {"content": [{"type":"text","text":"..."}, ...]}，
    但也可能直接给结构化数据，两种都兜住。
    """
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)

    parts = []
    for item in result.get("content", []) or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
        elif isinstance(item, dict) and item.get("type") == "resource":
            parts.append(str(item.get("resource", "")))
    if parts:
        return "\n".join(parts)

    # 没有 content 字段，就直接序列化整个 result
    return json.dumps(result, ensure_ascii=False)


def tool_result_json(result: dict):
    """尽量把工具返回解析成 JSON 对象；解析不了返回 None。

    文本里常见两种形态：
      · 纯 JSON
      · 带 markdown 代码围栏的 JSON（```json ... ```）
    """
    text = tool_result_text(result).strip()
    if not text:
        return None

    # 剥掉 ```json ... ``` 围栏
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 有些实现会把 JSON 夹在说明文字里，尝试截取最外层的 {...} 或 [...]
        for open_ch, close_ch in (("[", "]"), ("{", "}")):
            i, j = text.find(open_ch), text.rfind(close_ch)
            if 0 <= i < j:
                try:
                    return json.loads(text[i : j + 1])
                except json.JSONDecodeError:
                    continue
    return None
