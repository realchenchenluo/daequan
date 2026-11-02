"""
浏览器相关命令：登录一次 → 之后自动搜商家 / 读页面。

三条命令的分工
────────────────────────────────────────────
  登录浏览器   打开一个真浏览器让你自己扫码，登录态存在本机，之后复用
  搜商家 关键词  用你的登录态去搜，只读结果那一页的商家列表
  读页面       你自己点到某个商品页/店铺页，我读当前这一屏

为什么「搜商家」要登录、而首页不用
────────────────────────────────────────────
实测（2026-10）：
  · 美团外卖 H5 首页 /waimai/mindex/home —— 不登录也能看到附近商家列表
  · 美团外卖 H5 搜索 /waimai/mindex/search?keyword=… —— 302 到 /login?force=true
  · 饿了么 H5 首页 —— 直接跳登录墙

所以「不登录就看」最多只能看到系统推给你的附近几家，**指名搜某家店必须登录**。
这也是为什么这个功能需要你自己登录一次：不是我要你的账号，
是平台把搜索功能锁在登录后面，而没有任何合规的公开接口可以替代。

为什么读 DOM 而不是截图
────────────────────────────────────────────
读的是浏览器渲染后的文字，**没有 OCR 错字**，准确率 100%。
代价是依赖页面文字格式——所以解析器只认格式稳定的短标签（评分/月售/起送/
配送/分钟/km），认不出的就丢弃，绝不猜。
"""

from __future__ import annotations

from pathlib import Path

from .browser import (
    BrowserError,
    HOME_URLS,
    LOGIN_URLS,
    launch_login_window,
    open_session,
    read_current,
    read_page,
    read_search,
    search_url,
    wait_for_login,
)
from .config import PROJECT_ROOT
from .storelist import parse_store_list, render_stores

WARNING = """
  ⚠️ 使用前请确认你接受这几点：

    1. 这是用【你自己的账号、你自己的浏览器】去读【你自己能看到的页面】，
       不下载数据、不下单、不改任何东西。
    2. 但自动化访问平台页面，在多数平台的用户协议里是**不被允许**的。
       实际风险：弹验证码、账号被临时限制、页面改版后失效。
    3. 登录凭证存在本机 data/browser-profile/ 目录，**不会上传任何地方**。
       这个目录等同于你的登录态，别拷给别人，别提交到代码仓库。

  继续使用即表示你已知悉并自行承担上述风险。

"""


def _ask(msg: str) -> str:
    try:
        return input(msg)
    except (EOFError, KeyboardInterrupt):
        return ""


def cmd_browser_login(opts: dict) -> int:
    """打开一个浏览器窗口让你登录。默认**不等你**，你想什么时候登都行。

    为什么改成不等
    ────────────────────────────────────────
    早先的版本是「我开着窗口，最多等你 20 分钟，登不完就超时关窗」。
    实测那次等满了也没等到——然后窗口被关掉，等于把登录机会一起关掉。
    现在改成独立进程拉起 Chrome，跟本程序没有父子关系：
    你想什么时候登、登多久都行，登完自己关窗口，cookie 已经写进
    data/browser-profile/ 了，之后「搜商家」直接能用。

    如果想让我盯着确认登录成功，加 --等待 秒数（会改成自动发现模式）。
    """
    platform = opts.get("平台") or "美团"
    wait_s = int(opts.get("等待") or 0)

    keyword = (opts.get("关键词") or "").strip()
    if not keyword:
        extra = opts.get("_args") or []
        if extra:
            keyword = str(extra[0]).strip()

    override = opts.get("网址") or ""
    if override:
        url = override
    elif keyword:
        url = search_url(platform, keyword)
    else:
        url = LOGIN_URLS.get(platform) or HOME_URLS.get(platform, HOME_URLS["美团"])

    print(WARNING)

    # ── 默认路径：独立窗口，立刻返回 ──────────────────────
    if wait_s <= 0:
        print(f"  正在打开浏览器窗口（{platform}）……")
        ok, info = launch_login_window(PROJECT_ROOT, url)
        if not ok:
            print(f"  ⚠️ {info}，改用另一种方式（会等你登录完，最多 10 分钟）")
            print()
            wait_s = 600
        else:
            print(f"  ✅ 窗口已打开（{info}）")
            print()
            print("  ┌─ 接下来 ──────────────────────────────────────")
            if keyword:
                print(f"  │ 窗口里在搜「{keyword}」，没登录会跳到登录页。")
            else:
                print("  │ 登录入口一般在右下角「我的」，或者页面上的「登录」。")
            print("  │ 1. 输手机号 → 收验证码 → 登录")
            print("  │ 2. 如果弹出「拖动滑块」，请手动拖完（我不会绕过它）")
            print("  │ 3. 登录成功后，把这个浏览器窗口关掉")
            print("  └───────────────────────────────────────────────")
            print()
            print("  这个窗口跟我没关系了，你想登多久都行，我不催也不超时。")
            print("  登完关窗后，直接跑：")
            print(f"      python run.py 搜商家 {'麦当劳' if not keyword else keyword}")
            print()
            return 0

    # ── --等待 模式：我盯着，自动发现登录成功 ──────────────
    print(f"  （盯着模式：最多等 {wait_s // 60} 分钟）")
    try:
        pw, ctx = open_session(PROJECT_ROOT, headless=False)
    except BrowserError as e:
        print(f"  ✗ {e}")
        return 1

    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"  ✗ 打开页面失败：{e}")
            return 1

        print()
        print("  ┌─ 接下来请你在浏览器窗口里操作 ─────────────────")
        if keyword:
            print(f"  │ 正在尝试搜「{keyword}」。没登录的话会跳到登录页。")
            print("  │ 输入手机号 → 收验证码 → 登录。")
            print("  │ 如果弹出「拖动滑块」的验证，请手动拖完——我不会绕过它。")
        else:
            print("  │ 登录入口一般在右下角「我的」，或者页面上的「登录」。")
            print("  │ 输入手机号 → 收验证码 → 登录。")
            print("  │ 如果弹出「拖动滑块」的验证，请手动拖完——我不会绕过它。")
        print("  │ 登录完成后**什么都不用按**，我会自己发现。")
        print(f"  │ （最多等 {wait_s // 60} 分钟）")
        print("  └───────────────────────────────────────────────")
        print(flush=True)

        ok, msg = wait_for_login(
            ctx,
            timeout_s=wait_s,
            log=lambda s: print(f"  ⚠️ {s}", flush=True),
        )
        print()
        if not ok:
            print(f"  ✗ {msg}")
            print()
            return 2

        # 光靠"页面不像登录页"还不够，实测被坑过一次：
        # 页脚先渲染出来，1.5 秒后滑块才出现，于是误判成登录成功。
        # 所以这里再读一次真实页面，用**内容**说话。
        pg = [p for p in ctx.pages if not p.is_closed()]
        r = read_current(pg[-1], wait_ms=1200) if pg else None
        if r is None:
            print("  ✗ 浏览器被关掉了。")
            return 2
        if r.looks_captcha or r.looks_login:
            print("  ✗ 还没真正登录成功——页面上是登录墙或滑块验证。")
            print("     请重新跑一次，并在浏览器窗口里把滑块拖完 / 完成登录。")
            print()
            return 2

        print(f"  ✅ {msg}")
        print("  ✅ 登录态已保存到 data/browser-profile/（下次不用再登录）")
        print("     提示：登录态通常几天到几周过期，过期了重跑这条命令即可。")
        print()

        if keyword:
            stores = parse_store_list(r.text)
            print(f"  ── 搜「{keyword}」的结果 ──")
            print()
            print(render_stores(stores, keyword))
            if not stores:
                # 读不出来就把原文露几行：可能是没定位、或者版式变了
                print()
                print("  这一页实际显示的文字（前 15 行，用于判断原因）：")
                head = [l.strip() for l in r.text.splitlines() if l.strip()][:15]
                for line in head:
                    print(f"    {line[:70]}")
            print()
    except Exception as e:
        print(f"  ✗ {e}")
        return 1
    finally:
        try:
            ctx.close()
        finally:
            pw.stop()

    return 0


def cmd_read_page(opts: dict) -> int:
    """打开浏览器，让用户自己点到目标页面，然后读当前页面的文字。"""
    platform = opts.get("平台") or "美团"
    url = opts.get("网址") or HOME_URLS.get(platform, HOME_URLS["美团"])

    from .product import describe_product, parse_product_page

    print()
    print(f"  正在打开浏览器（{platform}）……")
    try:
        pw, ctx = open_session(PROJECT_ROOT, headless=False)
    except BrowserError as e:
        print(f"  ✗ {e}")
        return 1

    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)

        print()
        print("  请在浏览器里找到你想看的那个商品页（或店铺页），")
        print("  停在能看到价格的那一屏，然后回来按回车。")
        print("  想多读几个页面就重复：按回车读一次，再点下一个页面。")
        print("  直接输入 q 回车退出。")
        print()

        reads = 0
        while True:
            cmd = _ask("  按回车读取当前页面（q 退出）：").strip().lower()
            if cmd in ("q", "quit", "退出"):
                break

            try:
                r = read_page(page, page.url, wait_ms=1200)
            except BrowserError as e:
                print(f"  ✗ {e}")
                continue

            reads += 1
            print()
            print(f"  ── 第 {reads} 次读取 ──")
            print(f"  标题：{r.title[:60]}")
            print(f"  地址：{r.url[:90]}")

            for n in r.notes:
                print(f"  ⚠️ {n}")
            if r.looks_login or r.looks_captcha:
                # 被拦了就停，不尝试绕过
                print("  这一页读不到了，请先在浏览器里处理完登录/验证再继续。")
                print()
                continue

            info = parse_product_page(r.text)
            if info.get("price") is not None:
                print()
                print(f"  ✅ {describe_product(info)}")
            else:
                stores = parse_store_list(r.text)
                if stores:
                    print()
                    print("  这页看着是商家列表，读到这些店：")
                    print()
                    print(render_stores(stores))
                else:
                    print()
                    print("  没从这页认出价格，也没认出商家列表。可能是版式没覆盖。")
                    # 把前几行原文打出来，方便判断
                    head = [l.strip() for l in r.text.splitlines() if l.strip()][:12]
                    print("  页面上的文字（前 12 行）：")
                    for line in head:
                        print(f"    {line[:70]}")
            print()

        if reads:
            print(f"  本次共读了 {reads} 个页面。")
        print()

    except Exception as e:
        print(f"  ✗ {e}")
        return 1
    finally:
        try:
            ctx.close()
        finally:
            pw.stop()

    return 0


def cmd_search(opts: dict) -> int:
    """用自己的登录态搜一家店，读结果页的商家列表。"""
    keyword = (opts.get("关键词") or "").strip()
    if not keyword:
        # 「搜商家 麦当劳」里那个裸参数会落到 _args
        extra = opts.get("_args") or []
        if extra:
            keyword = str(extra[0]).strip()
    platform = opts.get("平台") or "美团"
    override = opts.get("网址") or ""

    if not keyword:
        print()
        print("  要搜什么店？例：python run.py 搜商家 麦当劳")
        print()
        return 1

    print()
    print(f"  正在 {platform} 上搜「{keyword}」……")
    print("  （只读这一页，不翻页、不批量抓取）")

    try:
        r = read_search(
            PROJECT_ROOT,
            platform,
            keyword,
            url_override=override,
            headless=False,
        )
    except BrowserError as e:
        print(f"  ✗ {e}")
        return 1

    print()
    print(f"  标题：{r.title[:60]}")
    print(f"  地址：{r.url[:100]}")
    for n in r.notes:
        print(f"  ⚠️ {n}")

    if r.looks_login:
        print()
        print("  这一页要求登录。先跑一次：python run.py 登录浏览器")
        print("  登录态会存到本机，之后搜商家就不用再登录了。")
        print()
        return 2

    if r.looks_captcha:
        print()
        print("  碰到验证码了。工具不会去绕——请手动处理完再重试这一条命令。")
        print()
        return 2

    stores = parse_store_list(r.text)
    print()
    print(render_stores(stores, keyword))
    if stores:
        print()
        print(
            "  提示：点进某一家店的商品页后，"
            "用「python run.py 读页面」可以读具体菜品价格。"
        )
    print()
    return 0
