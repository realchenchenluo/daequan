"""命令行入口。所有中文命令都配了英文别名，两个都能用。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from . import report
from .models import Coupon
from .rank import dedupe, rank
from .sources import fetch_all
from .sources import meituan_official as mt
from .store import append_history, load_auth, load_history

DEFAULT_SOURCES = [
    {
        "id": "free_aggregator",
        "type": "aggregator",
        "enabled": True,
        "label": "免费聚合口令源",
        "endpoint": "https://agskills.moontai.top/coupon/takeout",
    }
]

HELP = """
优惠猎手 —— 在美团 / 淘宝闪购 / 京东 上找大额券

常用：
  搜券                     把三个平台的券全抓一遍，按力度从大到小排
  搜券 --平台 美团          只看美团
  搜券 --关键词 奶茶        只找和奶茶相关的
  搜券 --只大额             过滤掉面额小的
  搜券 --网页               生成一个网页文件，双击就能看

每天用（推荐）：
  服务                     起一个本地网站，电脑和手机都能打开，随时刷新
  服务 --仅本机             只允许本机访问，同一个 WiFi 下的设备看不到
  服务 --端口 8888          换端口（默认 8788）
  服务 --打开               启动后自动打开浏览器

美团专属（力度最大，需要手机号登录一次）：
  登录                     发短信验证码，登录你的美团账号
  领券                     让美团把专属券直接发进你账号
  状态                     看当前登录状态
  退出                     删除本地保存的登录凭证

让它自己跑（都在你主动执行时才生效，程序不会擅自改动系统）：
  定时任务 --安装           装一个每天 09:00 自动抓券的任务
  定时任务 --安装 --时间 08:30   换时间
  定时任务 --状态           看装没装
  定时任务 --卸载           删掉，恢复原样
  快捷方式                 在桌面放两个图标（菜单 / 今日优惠券）

其他：
  源                       看有哪些数据源在用
  历史                     看以前搜过、领过什么
  帮助                     显示这份说明
"""


def _parse(argv: list[str]) -> tuple[str, dict]:
    """手工解析参数，因为要支持中文命令 + 中英混用的选项名。"""
    if not argv:
        return "搜券", {}

    cmd = argv[0]
    opts: dict = {
        "平台": None,
        "关键词": None,
        "前": 15,
        "全部": False,
        "json": None,
        "网页": False,
        "只大额": False,
        "源": None,
        "复制": False,
        "卸载": False,
        "状态": False,
        "时间": None,
        "端口": None,
        "仅本机": False,
        "打开": False,
        "输出": None,
    }

    i = 1
    while i < len(argv):
        a = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None

        if a in ("-p", "--平台", "--platform"):
            opts["平台"] = nxt
            i += 2
        elif a in ("-k", "--关键词", "--keyword"):
            opts["关键词"] = nxt
            i += 2
        elif a in ("-n", "--前", "--top"):
            try:
                opts["前"] = int(nxt)
            except (TypeError, ValueError):
                pass
            i += 2
        elif a in ("-a", "--全部", "--all"):
            opts["全部"] = True
            i += 1
        elif a in ("-j", "--json"):
            opts["json"] = nxt or "out/coupons.json"
            i += 2 if nxt and not nxt.startswith("-") else 1
        elif a in ("-w", "--网页", "--web"):
            opts["网页"] = True
            i += 1
        elif a in ("--只大额", "--big"):
            opts["只大额"] = True
            i += 1
        elif a in ("-s", "--源", "--source"):
            opts["源"] = nxt
            i += 2
        elif a in ("--复制", "--copy"):
            opts["复制"] = True
            i += 1
        elif a in ("--卸载", "--uninstall", "--删除"):
            opts["卸载"] = True
            i += 1
        elif a in ("--状态", "--status"):
            opts["状态"] = True
            i += 1
        elif a in ("--安装", "--install"):
            i += 1  # 默认动作就是安装，这个开关只是让命令读起来完整
        elif a in ("--时间", "--at"):
            opts["时间"] = nxt
            i += 2
        elif a in ("-P", "--端口", "--port"):
            try:
                opts["端口"] = int(nxt)
            except (TypeError, ValueError):
                pass
            i += 2
        elif a in ("--仅本机", "--local-only"):
            opts["仅本机"] = True
            i += 1
        elif a in ("--打开", "--open"):
            opts["打开"] = True
            i += 1
        elif a in ("-o", "--输出", "--out"):
            opts["输出"] = nxt
            i += 2
        else:
            i += 1

    return cmd, opts


def cmd_search(opts: dict, sources: list[dict]) -> int:
    t0 = time.time()
    result = fetch_all(sources, only=opts.get("源"))
    coupons = rank(result.coupons)
    coupons = dedupe(coupons)

    # 过滤
    if opts.get("平台"):
        want = opts["平台"]
        coupons = [c for c in coupons if want in c.platform or c.platform in want]
    if opts.get("关键词"):
        kw = opts["关键词"]
        coupons = [c for c in coupons if kw in c.title or kw in c.guideline]
    if opts.get("只大额"):
        # 有明确面额的，保留 10 元以上；只有关键词分的，保留高分项
        coupons = [
            c for c in coupons if (c.value is not None and c.value >= 10) or c.score >= 60
        ]

    report.print_header("优惠券搜索结果")
    report.print_coupons(
        coupons,
        top=None if opts.get("全部") else opts.get("前", 15),
    )
    report.print_footer(result, time.time() - t0, shown=len(coupons))

    if coupons:
        append_history(coupons[:50], "搜券", action="search")

    if opts.get("复制") and coupons:
        target = next((c for c in coupons if c.code), None)
        if target and report.copy_to_clipboard(target.code):
            print(f"  已把「{target.title}」的口令复制到剪贴板，直接去 App 粘贴即可。\n")

    if opts.get("json"):
        import os

        from .config import PROJECT_ROOT

        path = opts["json"]
        if not os.path.isabs(path):
            path = str(PROJECT_ROOT / path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        report.save_json(coupons, path)
        print(f"  JSON 已保存到 {path}\n")

    if opts.get("网页"):
        from .config import PROJECT_ROOT
        from .webpage import render

        if opts.get("输出"):
            out = Path(opts["输出"])
            if not out.is_absolute():
                out = PROJECT_ROOT / out
        else:
            out = PROJECT_ROOT / "out" / "优惠券.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(coupons, result), encoding="utf-8")
        print(f"  网页已生成：{out.resolve()}")
        print("  双击它就能用浏览器打开，点券码可以直接复制。\n")

    return 0 if coupons else 1


def cmd_login() -> int:
    print()
    print("  美团登录（券会直接发进你的美团账号）")
    print("  " + "─" * 46)
    print("  手机号和验证码只在你自己电脑上处理，不会上传到任何第三方。")
    print()

    phone = input("  请输入美团绑定的手机号：").strip()
    if not phone.isdigit() or len(phone) != 11:
        print("  手机号看起来不对，应该是 11 位数字。")
        return 1

    print("\n  正在发送验证码……")
    try:
        mt.send_sms(phone)
    except Exception as e:
        print(f"  发送失败：{e}")
        return 1

    print("  验证码已发送，请查看手机短信。")
    code = input("  请输入收到的验证码：").strip()
    if not code:
        print("  没输入验证码，已取消。")
        return 1

    try:
        mt.verify_sms(phone, code)
    except Exception as e:
        print(f"  登录失败：{e}")
        return 1

    print("\n  ✅ 登录成功！现在可以运行「领券」了。\n")
    return 0


def _meituan_ai_scene() -> str:
    """从 config.json 读美团推广渠道号。读不到就返回空串。"""
    from .config import load_config

    for src in load_config().get("sources", []):
        if src.get("id") == "meituan_official" or src.get("type") == "meituan_official":
            return (src.get("ai_scene") or "").strip()
    return ""


def cmd_claim() -> int:
    print()

    # 先查渠道号，再谈登录：否则用户白跑一次短信验证码
    # （美团短信每天限 5 次，浪费一次很烦）
    ai_scene = _meituan_ai_scene()
    if not ai_scene:
        print("  ⚠️ 还没配置美团推广渠道号，没法领券。先把这个搞定：")
        print()
        print("    1. 打开 https://union.meituan.com 免费注册")
        print("    2. 拿到你的推广位编号")
        print("    3. 填进 config.json 里 meituan_official 那条的 \"ai_scene\"")
        print()
        print("  为什么必须是你自己的编号：接口要求必填，而它决定你")
        print("  领券产生的佣金归谁。本工具不内置任何人的编号。")
        print()
        return 1

    auth = load_auth()
    if not auth.get("user_token"):
        print("  你还没登录。先运行：python run.py 登录")
        return 1

    print("  正在向美团领取专属券……")
    try:
        coupons, activity, link = mt.issue_coupons(auth["user_token"], ai_scene)
    except Exception as e:
        print(f"  失败了：{e}")
        return 1

    if coupons:
        report.print_header("领券成功，已进你的美团账号")
        report.print_coupons(coupons)
        append_history(coupons, "美团官方直发", action="claim")
    else:
        print("  今天没有新券可领了（通常每人每天一次）。")

    if activity:
        print(f"\n  顺便发现今日活动：{activity}")
        if link:
            print(f"  {link}")
    print()
    return 0


def cmd_status() -> int:
    auth = load_auth()
    token = auth.get("user_token")
    print()
    if not token:
        print("  美团：未登录")
    else:
        print(f"  美团：已登录（{auth.get('phone_masked', '未知号码')}）")
        print(f"  登录时间：{auth.get('login_at', '未知')}")
        print("  正在检查凭证是否还有效……")
        print("  " + ("✅ 有效" if mt.verify_token(token) else "❌ 已过期，请重新登录"))
    print()
    return 0


def cmd_logout() -> int:
    mt.logout()
    print("\n  已删除本地保存的登录凭证。\n")
    return 0


def cmd_history() -> int:
    rows = load_history()
    print()
    if not rows:
        print("  还没有记录。\n")
        return 0
    print(f"  最近 {min(len(rows), 30)} 条：")
    for r in rows[-30:]:
        print(f"    {r['time']}  [{r['platform']}] {r['title']}  {r['discount']}")
    print()
    return 0


def cmd_sources(sources: list[dict]) -> int:
    print()
    print("  当前配置的数据源：")
    for s in sources:
        flag = "✅ 启用" if s.get("enabled", True) else "⏸️  停用"
        print(f"    {flag}  {s.get('id'):<20} {s.get('label', '')}  ({s.get('type')})")
    print()
    print("  想增删数据源，直接编辑项目目录里的 config.json。")
    print()
    return 0


def cmd_auto() -> int:
    """定时任务用的静默模式：抓一遍 → 刷新网页 → 写一条日志。

    刻意不写领取历史：每天自动跑一次，如果每次都往 history.json 里塞 50 条，
    用不了几天就把有用的记录挤没了。
    """
    from datetime import datetime

    from .config import PROJECT_ROOT
    from .store import data_dir
    from .webpage import render

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = data_dir() / "auto.log"

    def log(line: str) -> None:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{stamp}  {line}\n")
        except Exception:
            pass

    try:
        result = fetch_all(_auto_sources())
        coupons = dedupe(rank(result.coupons))

        out = PROJECT_ROOT / "out" / "优惠券.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(coupons, result), encoding="utf-8")

        log(f"成功：抓到 {len(coupons)} 条，已写入 {out.name}")
        for e in result.errors:
            log(f"  数据源报错：{e}")
        for n in result.notes:
            log(f"  提示：{n}")
        return 0
    except Exception as e:
        log(f"失败：{type(e).__name__}: {e}")
        return 1


def _auto_sources() -> list[dict]:
    from .config import load_config

    return load_config().get("sources") or DEFAULT_SOURCES


def cmd_schedule(opts: dict) -> int:
    from . import scheduler

    if opts.get("卸载"):
        return scheduler.uninstall()
    if opts.get("状态"):
        return scheduler.status()
    return scheduler.install(opts.get("时间") or "09:00")


def cmd_shortcuts() -> int:
    from . import scheduler

    return scheduler.make_shortcuts()


def cmd_serve(opts: dict) -> int:
    from .server import DEFAULT_PORT, DEFAULT_TTL, serve

    return serve(
        port=opts.get("端口") or DEFAULT_PORT,
        host="127.0.0.1" if opts.get("仅本机") else "0.0.0.0",
        ttl=DEFAULT_TTL,
        open_browser=bool(opts.get("打开")),
    )


def cmd_menu(sources: list[dict]) -> int:
    """双击 .bat 时进来的交互菜单。

    菜单放在 Python 里而不是 .bat 里，是因为 cmd.exe 会按本地代码页（中文 Windows 是 GBK）
    解析批处理文件的字节，写中文进去必然乱码。Python 这边我们能把编码管住。
    """
    actions = {
        "1": ("搜券", lambda: cmd_search(_default_opts(), sources)),
        "2": ("搜券 + 生成网页", lambda: cmd_search(_default_opts(网页=True, 全部=True), sources)),
        "3": ("只看美团", lambda: cmd_search(_default_opts(平台="美团", 全部=True), sources)),
        "4": ("只找大额券", lambda: cmd_search(_default_opts(只大额=True, 全部=True), sources)),
        "5": ("登录美团", cmd_login),
        "6": ("领美团专属券", cmd_claim),
        "7": ("查看登录状态", cmd_status),
        "8": ("退出美团登录", cmd_logout),
        "9": ("查看数据源配置", lambda: cmd_sources(sources)),
        "10": ("查看领取历史", cmd_history),
        "11": ("让电脑每天自动抓一次（装定时任务）", lambda: cmd_schedule(_default_opts())),
        "12": ("在桌面放快捷方式", cmd_shortcuts),
        "13": ("启动本地网站（手机也能打开，Ctrl+C 停止）", lambda: cmd_serve(_default_opts())),
    }

    while True:
        print()
        print("  " + "=" * 46)
        print("     优惠猎手 · 美团 / 淘宝闪购 / 京东")
        print("  " + "=" * 46)
        print()
        for key in ("1", "2", "3", "4"):
            print(f"    {key:>2}.  {actions[key][0]}")
        print()
        for key in ("5", "6", "7", "8"):
            print(f"    {key:>2}.  {actions[key][0]}")
        print()
        for key in ("9", "10", "11", "12", "13"):
            print(f"    {key:>2}.  {actions[key][0]}")
        print()
        print("     0.  退出")
        print()

        try:
            choice = input("  请输入数字后回车：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice in ("0", "q", "Q", "exit", "退出"):
            return 0

        action = actions.get(choice)
        if action is None:
            continue

        try:
            action[1]()
        except KeyboardInterrupt:
            print("\n  已取消。")
        except Exception as e:
            print(f"\n  出错了：{e}")

        print()
        try:
            input("  按回车回到菜单……")
        except (EOFError, KeyboardInterrupt):
            return 0


def _default_opts(**kwargs) -> dict:
    opts = {
        "平台": None, "关键词": None, "前": 15, "全部": False,
        "json": None, "网页": False, "只大额": False, "源": None, "复制": False,
        "卸载": False, "状态": False, "时间": None,
    }
    opts.update(kwargs)
    return opts


_COMMANDS = {
    "搜券": "search", "搜": "search", "search": "search", "找券": "search",
    "登录": "login", "美团登录": "login", "login": "login",
    "领券": "claim", "美团领券": "claim", "claim": "claim",
    "状态": "status", "status": "status",
    "退出": "logout", "注销": "logout", "logout": "logout",
    "历史": "history", "history": "history",
    "源": "sources", "sources": "sources",
    "定时任务": "schedule", "定时": "schedule", "schedule": "schedule",
    "快捷方式": "shortcut", "shortcut": "shortcut",
    "服务": "serve", "网页服务": "serve", "serve": "serve",
    "菜单": "menu", "menu": "menu",
    "帮助": "help", "help": "help", "-h": "help", "--help": "help",
    # 供定时任务调用，不写历史、只刷新网页
    "自动": "auto", "auto": "auto",
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # 让它能吞下 Windows 上常见的编码意外
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    from .config import load_config

    cfg = load_config()
    sources = cfg.get("sources") or DEFAULT_SOURCES

    if not argv:
        print(HELP)
        return 0

    cmd_raw = argv[0]
    cmd = _COMMANDS.get(cmd_raw)

    if cmd is None:
        # 不是已知命令，那就当成搜券的关键词
        opts = {"平台": None, "关键词": cmd_raw, "前": 15, "全部": False,
                "json": None, "网页": False, "只大额": False, "源": None, "复制": False}
        _, extra = _parse(argv)
        opts.update({k: v for k, v in extra.items() if v not in (None, False)})
        return cmd_search(opts, sources)

    _, opts = _parse(argv)

    if cmd == "help":
        print(HELP)
        return 0
    if cmd == "menu":
        return cmd_menu(sources)
    if cmd == "auto":
        return cmd_auto()
    if cmd == "schedule":
        return cmd_schedule(opts)
    if cmd == "shortcut":
        return cmd_shortcuts()
    if cmd == "serve":
        return cmd_serve(opts)
    if cmd == "search":
        return cmd_search(opts, sources)
    if cmd == "login":
        return cmd_login()
    if cmd == "claim":
        return cmd_claim()
    if cmd == "status":
        return cmd_status()
    if cmd == "logout":
        return cmd_logout()
    if cmd == "history":
        return cmd_history()
    if cmd == "sources":
        return cmd_sources(sources)

    return 0
