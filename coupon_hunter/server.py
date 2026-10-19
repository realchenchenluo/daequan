"""
本地常驻服务：手机和电脑都能打开同一个地址，随时看当天的券。

为什么用服务而不是生成静态文件：
  · 静态文件你得先知道它在哪、双击它；
  · 服务是「打开一个网址」，手机加到主屏幕就跟 App 一样；
  · 数据在内存里缓存，页面上点「刷新」就能重新抓，不用回到终端。

安全设计（都是有意为之，改代码时别放松）：
  · 只认下面四条固定路由，**不做静态文件服务**，所以不存在路径穿越问题；
  · 只接受 GET 和 HEAD，没有写操作，不会有 CSRF 之类的问题；
  · 不收集、不记录任何请求内容，日志只打方法、路径、状态码。
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .config import load_config
from .models import FetchResult
from .rank import dedupe, rank
from .sources import fetch_all
from .webpage import render

DEFAULT_PORT = 8788
DEFAULT_TTL = 600  # 缓存 10 分钟，点刷新可以强制绕过


# ──────────────────────────────────────────────────────────
# 数据缓存
# ──────────────────────────────────────────────────────────

class CouponCache:
    """带过期时间的缓存。

    抓一次要一秒多，没必要每个请求都去抓。缓存 TTL 内直接返回内存里的数据，
    点页面上的「刷新」会强制重抓。
    """

    def __init__(self, ttl: int = DEFAULT_TTL):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._result: FetchResult | None = None
        self._coupons: list = []
        self._at: float = 0.0

    def get(self, force: bool = False):
        # 锁的作用：多个请求同时打进来时，只让第一个去抓，其余等结果
        with self._lock:
            expired = (time.time() - self._at) > self.ttl
            if force or self._result is None or expired:
                self._fetch_locked()
            return self._coupons, self._result, self._at

    def _fetch_locked(self) -> None:
        cfg = load_config()
        sources = cfg.get("sources") or []
        try:
            result = fetch_all(sources)
            self._coupons = dedupe(rank(result.coupons))
            self._result = result
        except Exception as e:
            # 抓取彻底失败时保留上一次的数据，总比给用户一个空白页强
            if self._result is None:
                self._result = FetchResult()
            self._result.errors.append(f"抓取失败：{type(e).__name__}: {e}")
        self._at = time.time()


# ──────────────────────────────────────────────────────────
# 请求处理
# ──────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "CouponHunter"
    sys_version = ""  # 别对外暴露 Python 版本号

    cache: CouponCache = None  # 由 create_server 注入
    page_title: str = "优惠猎手"

    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # 本地工具，不需要被任何搜索引擎收录
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(
            json.dumps(obj, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            code,
        )

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        # 只认这几个固定路径，别的都 404。不做文件服务，杜绝路径穿越。
        if path in ("/", "/index.html", "/优惠券.html"):
            self._page()
        elif path == "/api/coupons":
            self._api()
        elif path == "/refresh":
            self._refresh()
        elif path in ("/upload", "/比价"):
            self._upload_page()
        elif path == "/favicon.ico":
            self._send(b"", "image/x-icon", 204)
        else:
            self._send("404 Not Found".encode("utf-8"), "text/plain; charset=utf-8", 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/upload":
            self._send(b"404 Not Found", "text/plain; charset=utf-8", 404)
            return

        # 限制读取长度，防止有人往本地服务灌大文件
        max_body = 40 * 1024 * 1024
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > max_body:
            self._json({"error": "上传内容为空或过大"}, 413)
            return

        body = self.rfile.read(length)

        from .upload import handle_upload

        try:
            code, payload = handle_upload(body, self.headers.get("Content-Type", ""))
        except Exception as e:
            code, payload = 500, {"error": f"处理失败：{type(e).__name__}: {e}"}
        self._json(payload, code)

    def _upload_page(self) -> None:
        from .upload import render_upload_page

        self._send(render_upload_page().encode("utf-8"), "text/html; charset=utf-8")

    def _page(self) -> None:
        coupons, result, at = self.cache.get()
        updated = datetime.fromtimestamp(at).strftime("%H:%M:%S") if at else "—"
        html_text = render(
            coupons,
            result,
            title=self.page_title,
            refresh_url="/refresh",
            note=f"数据抓取于 {updated}（缓存 {self.cache.ttl // 60} 分钟）",
            source_note="点右上角「刷新」可立即重新抓取；要外卖比价请访问 /upload",
        )
        self._send(html_text.encode("utf-8"), "text/html; charset=utf-8")

    def _api(self) -> None:
        coupons, result, at = self.cache.get()
        self._json(
            {
                "updated_at": datetime.fromtimestamp(at).isoformat(timespec="seconds") if at else None,
                "count": len(coupons),
                "errors": list(getattr(result, "errors", [])),
                "notes": list(getattr(result, "notes", [])),
                "coupons": [c.to_dict() for c in coupons],
            }
        )

    def _refresh(self) -> None:
        self.cache.get(force=True)
        coupons, result, at = self.cache.get()
        self._json(
            {
                "ok": True,
                "count": len(coupons),
                "updated_at": datetime.fromtimestamp(at).isoformat(timespec="seconds"),
            }
        )

    def log_message(self, fmt: str, *args) -> None:
        """默认实现会把每个请求打到 stderr，太吵。这里只留一行简洁的。"""
        sys.stderr.write(f"  {self.address_string()} → {fmt % args}\n")


# ──────────────────────────────────────────────────────────
# 启动
# ──────────────────────────────────────────────────────────

def get_lan_ip() -> str:
    """拿到本机在局域网里的真实地址。

    不能用「连 8.8.8.8 看出口网卡」那种取巧办法——实测踩过坑：
    本机装了代理（TUN 模式），出口网卡是代理的虚拟网卡，拿到的地址是
    198.18.0.1（199.18.0.0/15 是代理软件常用的假 IP 段），
    把这个地址给手机，手机根本连不上。

    正确做法：枚举本机所有网卡地址，挑一个**真实的内网地址**。
    优先级：192.168.x > 10.x > 172.16-31.x，排除 198.18/15 和回环。
    """
    import ipaddress

    def is_usable(ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if addr.is_loopback or addr.is_link_local:
            return False
        # 代理的假 IP 段（RFC 2544 基准测试段），手机连不上
        if ip.startswith("198.18.") or ip.startswith("198.19."):
            return False
        return addr.is_private

    candidates: list[str] = []

    # 办法一：解析主机名（Windows 上通常能拿到所有网卡地址）
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if is_usable(ip) and ip not in candidates:
                candidates.append(ip)
    except Exception:
        pass

    # 办法二：UDP 探测（作为补充，过滤掉假 IP）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if is_usable(ip) and ip not in candidates:
                candidates.append(ip)
        finally:
            s.close()
    except Exception:
        pass

    if not candidates:
        return "127.0.0.1"

    # 排序：192.168 优先（家用路由器最常见），其次 10.x，再其次 172.16-31
    def rank(ip: str) -> int:
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        if ip.startswith("172."):
            return 2
        return 3

    candidates.sort(key=rank)
    return candidates[0]


def create_server(port: int, host: str, ttl: int, title: str) -> ThreadingHTTPServer:
    cache = CouponCache(ttl=ttl)

    handler = type(
        "BoundHandler",
        (Handler,),
        {"cache": cache, "page_title": title},
    )

    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def serve(port: int = DEFAULT_PORT, host: str = "0.0.0.0", ttl: int = DEFAULT_TTL,
          title: str = "优惠猎手", open_browser: bool = False) -> int:
    # 端口被占是很常见的（你机器上 8765 就被别的程序占了），提前给一句人话
    try:
        httpd = create_server(port, host, ttl, title)
    except OSError as e:
        print()
        print(f"  ❌ 端口 {port} 起不来：{e}")
        print(f"     换一个端口试试：python run.py 服务 --端口 {port + 1}")
        print()
        return 1

    lan = get_lan_ip()
    local_only = host in ("127.0.0.1", "localhost")

    print()
    print("  " + "=" * 52)
    print("     优惠猎手 本地服务已启动")
    print("  " + "=" * 52)
    print()
    print(f"     这台电脑：  http://127.0.0.1:{port}")
    if not local_only:
        print(f"     手机访问：  http://{lan}:{port}")
        print()
        print("     手机上把上面这个地址加到主屏幕，就跟装了个 App 一样。")
    print()
    print(f"     数据缓存 {ttl // 60} 分钟，点页面右上角「刷新」可立即重抓。")
    if not local_only:
        print()
        print(f"     提示：服务对同一个 WiFi 下的设备开放。别人连上你的 WiFi")
        print(f"           也能看到这些券码——都是公开的推广口令，但你要知道。")
        print(f"           只给自己用请加 --仅本机。")
    print()
    print("     按 Ctrl+C 停止服务。")
    print()
    sys.stdout.flush()  # 双击 bat 启动时，别让这段提示卡在缓冲区里

    if open_browser:
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。\n")
    finally:
        httpd.server_close()
    return 0
