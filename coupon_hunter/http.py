"""
统一的 HTTP 请求封装（只用标准库 urllib）。

为什么单独写一层：
  - 免去用户 pip install requests 的麻烦；
  - 统一超时、重试、UA、错误处理；
  - 方便在某些站点证书异常时降级（verify=False 的等价物）。
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

# 伪装成 iPhone 上的 Safari，很多接口对默认的 python-urllib UA 会直接拒绝
DEFAULT_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


class HttpError(Exception):
    """网络请求失败。message 是给人看的中文说明。"""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body


def _build_ssl_context(verify: bool) -> ssl.SSLContext:
    if verify:
        return ssl.create_default_context()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def request(
    url: str,
    *,
    method: str = "GET",
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
    timeout: float = 15.0,
    verify: bool = True,
    retries: int = 2,
) -> str:
    """发起 HTTP 请求，返回响应正文字符串。

    retries 表示失败后额外重试的次数（默认 2，即总共最多请求 3 次）。
    只有网络层错误才重试；服务器返回 4xx/5xx 不重试（重试也没用）。
    """
    if params:
        sep = "&" if urllib.parse.urlparse(url).query else "?"
        url = url + sep + urllib.parse.urlencode(params)

    data = None
    hdrs = {
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
        hdrs["X-Requested-With"] = "XMLHttpRequest"
    if headers:
        hdrs.update(headers)

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            # 不用 urlopen 的全局 opener，避免受系统代理环境影响太大
            ctx = _build_ssl_context(verify)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read()
                return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            # 服务器有响应，说明网络是通的。把响应体读出来，很多接口会用 4xx 携带业务错误码
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            raise HttpError(f"服务器返回 HTTP {e.code}", status=e.code, body=body) from e
        except urllib.error.URLError as e:
            last_err = e
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise HttpError(f"网络连接失败：{e.reason}") from e
        except TimeoutError as e:
            last_err = e
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise HttpError("请求超时") from e

    raise HttpError(f"网络连接失败：{last_err}")


def get_json(url: str, **kwargs) -> dict:
    """GET 并解析 JSON。解析失败会抛出带原文的错误，方便排查。"""
    text = request(url, method="GET", **kwargs)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        snippet = text[:200].replace("\n", " ")
        raise HttpError(f"返回内容不是合法 JSON（原文开头：{snippet}）") from e


def post_json(url: str, body: dict, **kwargs) -> dict:
    """POST JSON 并解析 JSON 响应。"""
    text = request(url, method="POST", json_body=body, **kwargs)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        snippet = text[:200].replace("\n", " ")
        raise HttpError(f"返回内容不是合法 JSON（原文开头：{snippet}）") from e
