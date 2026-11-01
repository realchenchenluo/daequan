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

from .browser import BrowserError, open_session, read_page, read_search
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

HOME_URLS = {
    "美团": "https://h5.waimai.meituan.com/waimai/mindex/home",
    "淘宝闪购": "https://h5.ele.me/",
    "饿了么": "https://h5.ele.me/",
}


def _ask(msg: str) -> str:
    try:
        return input(msg)
    except (EOFError, KeyboardInterrupt):
        return ""


def cmd_browser_login(opts: dict) -> int:
    """打开一个可交互的浏览器，让用户自己扫码登录。"""
    platform = opts.get("平台") or "美团"
    url = opts.get("网址") or HOME_URLS.get(platform, HOME_URLS["美团"])

    print(WARNING)

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
        print("  浏览器已经打开了，请在里面完成登录（一般是点「我的」→ 手机号/扫码登录）。")
        print("  登录成功后**不要关浏览器**，回到这里按回车。")
        print()
        _ask("  登录好了就按回车……")
        print()
        print("  已保存登录态到 data/browser-profile/（下次不用再登录）。")
        print("  提示：登录态通常几天到几周过期，过期了重新跑这条命令即可。")
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
