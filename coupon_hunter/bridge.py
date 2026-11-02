"""
本地界面和浏览器之间的桥。

为什么必须单独开一个线程
────────────────────────────────────────────
Playwright 的 sync API 有一个硬性要求：**所有调用必须在创建它的那个线程里**。
而本地服务（ThreadingHTTPServer）是「一个请求一个线程」，
所以在 HTTP 处理线程里直接调 Playwright，一定会炸：
    greenlet.error: Cannot switch to a different thread

所以这里做成一个**专属工作线程**：它独占 Playwright，别的线程只能
往队列里扔命令、等结果。HTTP 那边看到的就是普通的同步函数调用。

为什么浏览器窗口是可见的
────────────────────────────────────────────
无头浏览器更容易被识别成机器人，而且需要你自己登录一次、还要能看见页面
再点「抓取」。所以这个窗口是真实可见的 Chrome，用的是和命令行走廊
同一份登录态目录（data/browser-profile/）。

⚠️ 注意这条通道的性质：它**持有你的登录态**。这和「粘贴菜单」那条
（工具只拿一段文字）不一样。界面上两条路都提供，你自己按需要选。
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from .browser import BrowserError, HOME_URLS, open_session, search_url
from .discount import parse_store_promos
from .menu_dom import SNAPSHOT_JS, extract_from_snapshot, nodes_from_snapshot
from .menu import render_menu, to_offer_spec


class Bridge:
    """一个常驻的浏览器窗口 + 命令队列。"""

    def __init__(self, root: Path):
        self._root = Path(root)
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # 给界面读的状态。只由工作线程写，读的时候拿的是快照，不用加锁。
        self.state: dict = {
            "open": False,
            "url": "",
            "title": "",
            "platform": "",
            "started_at": 0.0,
            # 最近一次抓取读到的店铺优惠（满减/无门槛/折扣），
            # 「算最高折扣」那一页可以直接拿来用，不用再抓一次。
            # 注意：关掉浏览器时不清理这两个字段——用户往往是抓完就关窗，
            # 然后才去算账。
            "store_promos": [],
            "grabbed_title": "",
        }

    # ── 对外接口 ────────────────────────────────────────
    def call(self, cmd: str, timeout: float = 120.0, **kwargs) -> dict:
        """投递一个命令并等结果。超时不会杀掉浏览器，只是这次请求放弃等待。"""
        self._ensure_thread()
        item = {
            "cmd": cmd,
            "kwargs": kwargs,
            "done": threading.Event(),
            "result": None,
        }
        self._q.put(item)
        if not item["done"].wait(timeout):
            return {
                "ok": False,
                "error": (
                    "浏览器操作超时（页面可能卡住了）。\n"
                    "  可以点「关闭浏览器」重来一次。"
                ),
            }
        return item["result"] or {"ok": False, "error": "内部错误：没有拿到结果"}

    def shutdown(self) -> None:
        try:
            self._q.put(None)
        except Exception:
            pass

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker, name="coupon-browser-bridge", daemon=True
            )
            self._thread.start()

    # ── 工作线程 ────────────────────────────────────────
    def _worker(self) -> None:
        pw = None
        ctx = None
        page = None

        def teardown() -> None:
            nonlocal pw, ctx, page
            if ctx is not None:
                try:
                    ctx.close()
                except Exception:
                    pass
            if pw is not None:
                try:
                    pw.stop()
                except Exception:
                    pass
            pw = ctx = page = None
            self.state.update(open=False, url="", title="", platform="", started_at=0.0)

        while True:
            item = self._q.get()
            if item is None:
                teardown()
                return

            cmd = item["cmd"]
            kw = item["kwargs"] or {}
            try:
                if cmd == "open":
                    platform = kw.get("platform") or "美团"
                    override = kw.get("url") or ""
                    keyword = (kw.get("keyword") or "").strip()

                    if override:
                        url = override
                    elif keyword:
                        url = search_url(platform, keyword)
                    else:
                        url = HOME_URLS.get(platform, HOME_URLS["美团"])

                    if ctx is None:
                        pw, ctx = open_session(self._root, headless=False)
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(1500)
                    self.state.update(
                        open=True,
                        url=page.url,
                        title=(page.title() or "")[:80],
                        platform=platform,
                        started_at=time.time(),
                    )
                    item["result"] = {
                        "ok": True,
                        "url": page.url,
                        "title": page.title() or "",
                        "platform": platform,
                        "hint": "现在在浏览器窗口里点进你想看的那家店，然后回来点「抓取当前页」。",
                    }

                elif cmd == "grab":
                    if page is None or ctx is None:
                        item["result"] = {
                            "ok": False,
                            "error": "浏览器还没打开。先点「打开浏览器」。",
                        }
                    elif page.is_closed():
                        teardown()
                        item["result"] = {
                            "ok": False,
                            "error": "浏览器窗口被关掉了。重新点「打开浏览器」即可。",
                        }
                    else:
                        snapshot = page.evaluate(SNAPSHOT_JS)
                        ex = extract_from_snapshot(snapshot or {})

                        # 顺带把店铺满减读出来。页面上「满30减5」这种小字
                        # 本身就是一个短节点，把节点文字拼起来再做正则是可行的，
                        # 不需要额外请求、也不用再解析一遍 DOM。
                        page_text = " ".join(
                            n.text for n in nodes_from_snapshot(snapshot or {})
                        )
                        promos = parse_store_promos(page_text)
                        promo_dicts = [
                            {
                                "text": p.text,
                                "kind": p.kind,
                                "describe": p.describe(),
                                "threshold": p.threshold,
                                "value": p.value,
                            }
                            for p in promos
                        ]

                        self.state.update(
                            url=page.url,
                            title=(page.title() or "")[:80],
                            store_promos=promo_dicts,
                            grabbed_title=ex.menu.store or (page.title() or "")[:80],
                        )
                        item["result"] = {
                            "ok": True,
                            "url": ex.url,
                            "title": ex.title,
                            "store": ex.menu.store,
                            "source": ex.menu.source,
                            "notes": ex.notes,
                            "price_nodes": ex.price_nodes,
                            "dishes": [
                                {
                                    "name": d.name,
                                    "price": d.price,
                                    "original": d.original,
                                    "saved": d.saved,
                                }
                                for d in ex.menu.dishes
                            ],
                            "store_promos": promo_dicts,
                            "total": ex.menu.total,
                            "original_total": ex.menu.original_total,
                            "text": render_menu(ex.menu),
                            "offer_spec": to_offer_spec(ex.menu),
                        }

                elif cmd == "close":
                    teardown()
                    item["result"] = {"ok": True}

                elif cmd == "status":
                    item["result"] = {"ok": True, **self.state}

                else:
                    item["result"] = {"ok": False, "error": f"未知命令：{cmd}"}

            except BrowserError as e:
                teardown()
                item["result"] = {"ok": False, "error": str(e)}
            except Exception as e:  # noqa: BLE001
                item["result"] = {
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                }
            finally:
                item["done"].set()
