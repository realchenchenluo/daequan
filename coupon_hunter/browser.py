"""
读外卖平台页面 —— 用你自己的浏览器登录态，本地读取，凭证不出本机。

⚠️ 先说清楚：这和你自己用手机点外卖在规则意义上不完全一样
────────────────────────────────────────────
自动化访问平台页面，多数平台的用户协议里是不允许的。这条路的实际风险：
  · 平台可能弹验证码，工具就停在那儿
  · 频繁使用可能触发风控，账号被临时限制
  · 页面一改版，选择器就失效
本工具已尽量把频率压到最低（一次一个商家、不并发、不批量），
但**风险由你自己承担**。不想承担就别用这个功能，用截图识别那条路。

为什么必须用「你自己的浏览器」
────────────────────────────────────────────
实测结果（2026-10）：
  · 美团内部接口 wmapi.meituan.com/api/v7/poi/search → HTTP 403
    返回「Forbidden, Contact: it.mtgsig@meituan.com」——那是美团安全团队的邮箱，
    说明接口要签名，裸调一律被拦。GitHub 上那些开源项目就是死在这里。
  · 饿了么 restapi/shopping/v3/* → 302 跳登录
  · 无登录的浏览器访问 i.meituan.com → 直接弹滑块验证

所以只剩一条路：**你本人登录过的浏览器**。空壳浏览器过不了的门，
一个登着账号的老主顾能大摇大摆走进去——这是实测出来的。

设计要求（都是为了把风险压到最低）
────────────────────────────────────────────
  · 凭证永远不出本机：用独立的浏览器配置目录，你自己扫码登录，工具只读页面
  · 只读，不写：不下单、不加购物车、不改任何东西
  · 单次单商家：不并发、不遍历、不做批量采集
  · 一遇到登录页/验证码就停，不尝试绕过
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

PROFILE_DIR_NAME = "browser-profile"

# 各平台的登录页。直接打开这个页面，用户看到的第一个东西就是登录表单。
LOGIN_URLS = {
    "美团": "https://h5.waimai.meituan.com/login",
    "饿了么": "https://h5.ele.me/login",
    "淘宝闪购": "https://h5.ele.me/login",
}


class BrowserError(Exception):
    """浏览器层面的问题，message 直接给用户看。"""


@dataclass
class PageRead:
    """一次页面读取的结果。"""

    url: str = ""
    title: str = ""
    text: str = ""
    looks_login: bool = False
    looks_captcha: bool = False
    notes: list[str] = field(default_factory=list)


# 判断「是不是被拦住了」的特征
#
# 注意「验证码」这三个字**不能**单独用来判断滑块验证：
# 正常的短信登录页写着「发送验证码 / 验证码登录」，会被误判成验证码拦截。
# 所以这里只放滑块/人机核验这类**只出现在真拦截页**的词。
LOGIN_HINTS = ("登录", "扫码登录", "请先登录", "密码登录", "验证码登录")
CAPTCHA_HINTS = (
    "拖动滑块",
    "滑块",
    "滑动验证",
    "人机验证",
    "安全验证",
    "身份核实",
    "请完成验证",
    "按住左边滑块",
)


def classify(title: str, text: str) -> tuple[bool, bool]:
    """判断一页是「要登录」还是「弹了验证码」。返回 (要登录, 有验证码)。

    验证码优先——真弹滑块时页面上往往也写着「登录」，不能糊成登录墙，
    否则用户会以为登一下就好，实际上不去手动拖一下永远过不去。

    只扫标题 + 正文前 1500 字：正文后段可能出现「验证码」之类的无关字样
    （比如页脚的用户协议说明），扫全文会误判。
    """
    head = title + "\n" + text[:1500]
    looks_captcha = any(k in head for k in CAPTCHA_HINTS)
    looks_login = any(k in head for k in LOGIN_HINTS) and not looks_captcha
    return looks_login, looks_captcha


# 只认 URL 的**路径部分**，不看查询串。
# 因为登录跳转的 back_url 参数里也带着 "/login" 字样，
# 扫整个 URL 会把"已经登录成功、只是地址里带了回跳参数"误判成还在登录页。
_LOGIN_PATH_MARKERS = ("/login", "/passport", "/signin", "/sign_in")


def looks_like_login_url(url: str) -> bool:
    """这个地址是不是登录页。"""
    try:
        path = urlsplit(url or "").path.lower()
    except ValueError:
        return False
    return any(m in path for m in _LOGIN_PATH_MARKERS)


def _profile_dir(root: Path) -> Path:
    d = root / "data" / PROFILE_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise BrowserError(
            "没装 playwright。先运行：\n"
            "  python -m pip install playwright\n"
            "  python -m playwright install chromium"
        ) from e
    return sync_playwright


def open_session(root: Path, headless: bool = False, timeout: int = 30000):
    """打开一个带**持久化登录态**的浏览器。

    返回 (playwright, context)。用完记得 context.close() / pw.stop()。

    headless=False 是刻意的：无头浏览器更容易被识别成机器人，
    而且首次登录需要你看到窗口扫码。真要用无头，得自己承担更大被拦的概率。

    持久化目录 data/browser-profile 会记住登录态，所以只需登录一次。
    ⚠️ 这个目录里存着你的登录 cookie，**不要拷给别人**，也不要提交到代码仓库
    （.gitignore 已经把它排除了）。
    """
    sync_playwright = _playwright()
    pw = sync_playwright().start()
    try:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(_profile_dir(root)),
            headless=headless,
            locale="zh-CN",
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
    except Exception as e:
        pw.stop()
        msg = str(e)
        # 同一个登录态目录同时只能被一个浏览器占用。
        # 上一轮的浏览器没关干净时，Chromium 报的错很难看懂，这里翻译成人话。
        if "ProcessSingleton" in msg or "SingletonLock" in msg or "already in use" in msg:
            raise BrowserError(
                "登录态目录正被另一个浏览器占着。先把之前打开的那个浏览器窗口关掉，再重试。\n"
                "（如果确定没有窗口了，等一下再试——进程退出有时要几秒。）"
            ) from e
        raise BrowserError(f"浏览器启动失败：{msg}") from e
    return pw, ctx


def read_current(page, wait_ms: int = 800) -> PageRead:
    """读**当前这一屏**的文字，不做任何跳转。

    和 read_page 的区别很关键：登录之后页面已经停在搜索结果上了，
    这时再 goto 一次等于二次请求——没必要，也平白多一次访问。
    """
    out = PageRead()
    try:
        if wait_ms:
            page.wait_for_timeout(wait_ms)
        out.title = page.title() or ""
        out.text = page.locator("body").inner_text(timeout=8000)[:20000]
        out.url = page.url
    except Exception as e:
        raise BrowserError(f"读页面失败：{e}") from e

    # 判断是否被拦
    out.looks_login, out.looks_captcha = classify(out.title, out.text)

    if out.looks_captcha:
        out.notes.append("页面弹了验证码/滑块。工具不会尝试绕过——请手动完成后重试。")
    elif out.looks_login:
        out.notes.append("页面要求登录。先运行「python run.py 登录浏览器」完成登录。")
    elif len(out.text.strip()) < 80:
        out.notes.append("页面几乎是空的，可能没加载出来，或者需要登录。")

    return out


def read_page(page, url: str, wait_ms: int = 3500) -> PageRead:
    """打开一个页面并读它的可见文字。"""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        raise BrowserError(f"打开页面失败：{e}") from e
    return read_current(page, wait_ms)


def _snapshot(page) -> tuple[str, str]:
    """取当前页的标题和正文开头。取不到就当空，不抛异常。"""
    try:
        title = page.title() or ""
    except Exception:
        title = ""
    try:
        text = page.locator("body").inner_text(timeout=5000)[:1500]
    except Exception:
        text = ""
    return title, text


def wait_for_login(
    ctx,
    timeout_s: int = 600,
    poll_ms: int = 1500,
    log=None,
    stable_checks: int = 3,
) -> tuple[bool, str]:
    """等你在这个浏览器里登录完，**自动发现**，不用按回车。

    判断依据：页面地址不是登录页、内容里没有登录墙/验证码，
    并且**连续稳定 stable_checks 次**都是这个样子。

    为什么要"连续稳定"而不是"看一眼就断言"
    ────────────────────────────────────────
    实测踩过：第一次搜「麦当劳」时，页面先渲染出美团页脚（非空、无登录字样），
    1.5 秒后才弹出「身份核实 / 请按照说明拖动滑块」。
    只看一眼就断言成功，等于把一张验证码页当成登录成功，后面读出来的全是垃圾。

    碰到验证码**不会失败退出**——那等于把用户唯一能救回来的机会掐掉。
    它会通过 log 提醒一次，然后继续等，等你自己把滑块拖完。

    全程只读当前标签页的地址和文字，**不额外发任何请求**。
    """
    deadline = time.monotonic() + max(3, int(timeout_s))
    last_sig = None
    stable = 0
    told_captcha = False

    while time.monotonic() < deadline:
        pages = [p for p in ctx.pages if not p.is_closed()]
        page = pages[-1] if pages else None
        if page is None:
            return False, "浏览器被关掉了，登录态没保存上。"

        try:
            url = page.url
        except Exception:
            return False, "浏览器被关掉了，登录态没保存上。"

        title, text = _snapshot(page)
        login_wall, captcha = classify(title, text)

        if captcha:
            if not told_captcha:
                told_captcha = True
                if log:
                    log("页面上出现了滑块/验证码——请在浏览器窗口里手动拖一下，我继续等。")
            stable, last_sig = 0, None
        elif looks_like_login_url(url) or login_wall or not text.strip():
            # 还在登录页、或者页面是空壳，继续等
            stable, last_sig = 0, None
        else:
            sig = url + "|" + text[:60]
            if sig == last_sig:
                stable += 1
            else:
                last_sig, stable = sig, 1
            if stable >= stable_checks:
                return True, f"登录成功（当前页面：{title[:30] or url[:50]}）"

        try:
            page.wait_for_timeout(poll_ms)
        except Exception:
            # 页面在切换中会短暂抛错，等一下再来
            time.sleep(poll_ms / 1000)

    if told_captcha:
        return False, (
            f"等了 {int(timeout_s)} 秒，滑块/验证码一直没有被处理。\n"
            "  重新跑这条命令，然后在弹出的浏览器窗口里把滑块拖完即可。"
        )
    return False, (
        f"等了 {int(timeout_s)} 秒还没登录成功。\n"
        "  可能原因：还没输完验证码、验证码收不到、或者浏览器窗口被关掉了。\n"
        "  重新跑一次这条命令即可，登录态目录不会丢。"
    )


# 各平台的搜索结果页地址。{kw} 会被替换成 URL 编码后的关键词。
#
# 美团这条是**实测确认过路由存在**的：未登录访问会被 302 到
# /login?force=true&back_url=…（说明登录后会正常落在搜索页）。
# 饿了么那边未登录一律跳登录墙，没法在不登录的情况下确认路由格式，
# 所以标成「未验证」——真跑不通就用 --网址 自己指定。
SEARCH_URLS = {
    "美团": "https://h5.waimai.meituan.com/waimai/mindex/search?keyword={kw}",
    "饿了么": "https://h5.ele.me/search?keyword={kw}",
    "淘宝闪购": "https://h5.ele.me/search?keyword={kw}",
}

UNVERIFIED_PLATFORMS = ("饿了么", "淘宝闪购")


def search_url(platform: str, keyword: str, override: str = "") -> str:
    """拼出搜索页地址。override 非空时优先用它（支持 {kw} 占位）。"""
    from urllib.parse import quote

    kw = quote(keyword, safe="")
    tpl = override or SEARCH_URLS.get(platform)
    if not tpl:
        raise BrowserError(
            f"没有 {platform} 的搜索地址。用「搜商家 {keyword} --网址 <完整地址>」自己指定。"
        )
    return tpl.replace("{kw}", kw) if "{kw}" in tpl else tpl


def read_search(
    root: Path,
    platform: str,
    keyword: str,
    url_override: str = "",
    headless: bool = False,
    wait_ms: int = 6000,
) -> PageRead:
    """在已登录的浏览器里搜一个商家关键词，返回搜索页读到的内容。

    只读一件事：这一页上的商家列表。不翻页、不滚动加载更多、不并发。
    被拦（登录墙/验证码）就原样返回，由调用方决定停下还是让用户处理——
    这里绝不尝试绕过。
    """
    url = search_url(platform, keyword, url_override)
    pw, ctx = open_session(root, headless=headless)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        out = read_page(page, url, wait_ms=wait_ms)
        if platform in UNVERIFIED_PLATFORMS and not (out.looks_login or out.looks_captcha):
            out.notes.append(
                f"{platform} 的搜索地址没验证过，读不到东西就把 --网址 指到搜索结果页。"
            )
        return out
    finally:
        try:
            ctx.close()
        finally:
            pw.stop()


def check_login_state(root: Path, test_url: str) -> tuple[bool, str]:
    """快速检查登录态是否还有效。返回 (是否已登录, 说明)。"""
    pw, ctx = open_session(root)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        r = read_page(page, test_url, wait_ms=2500)
        if r.looks_captcha:
            return False, "碰到验证码，需要你手动处理"
        if r.looks_login:
            return False, "还没登录（页面要求登录）"
        return True, f"看起来是登录状态（标题：{r.title[:40]}）"
    finally:
        try:
            ctx.close()
        finally:
            pw.stop()
