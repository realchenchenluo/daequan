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

算账（不用联网，不读任何券源）：
  叠券                      算「叠完所有券之后实际付多少」，会告诉你每步怎么减的
  叠券 --价 399 --平台 京东 --券 "满减,300,50" --券 "折扣,0.9" --plus
                            一次性算，不进交互
  比价                      同一件商品在几个平台的到手价对比，排出最便宜的那个
  外卖比价                  同一家外卖在美团/饿了么/京东，算上券和配送费谁最便宜
  商品 <截图>               发一张商品页截图，看这单多少钱、能用什么券
  关注                      看关注清单（券自动更新，到目标价就提醒）
  关注 --名 "某耳机" --价 "京东=399,拼多多=359" --目标 350   加一个

麦当劳官方券（全项目唯一的官方接口，Token 免费）：
  麦当劳                   连一下官方服务，看能领到什么券（诊断用）
  麦当劳 --工具            列出官方开放的 24 个工具
  麦当劳 --调用 <工具名>    调指定的工具看原始返回

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
        "令牌": None,
        "工具": False,
        "调用": None,
        "价": None,
        "券": [],
        "方案": [],
        "plus": False,
        "目标": None,
        "类型": None,
        "备注": None,
        "删除": None,
        "清空": False,
        "截图": [],
        "图片": None,
        "名": None,
        "方案": None,
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
        elif a in ("--令牌", "--token"):
            opts["令牌"] = nxt
            i += 2
        elif a in ("--工具", "--tools"):
            opts["工具"] = True
            i += 1
        elif a in ("--调用", "--call"):
            opts["调用"] = nxt
            i += 2
        elif a in ("--价", "--price"):
            # 两种用法：--价 399（叠券用数字）；--价 "京东=399,拼多多=359"（关注清单用）
            try:
                opts["价"] = float(nxt)
            except (TypeError, ValueError):
                opts["价"] = nxt
            i += 2
        elif a in ("--目标", "--target"):
            try:
                opts["目标"] = float(nxt)
            except (TypeError, ValueError):
                pass
            i += 2
        elif a in ("--类型", "--kind"):
            opts["类型"] = nxt
            i += 2
        elif a in ("--备注", "--note"):
            opts["备注"] = nxt
            i += 2
        elif a in ("--删除", "--rm"):
            opts["删除"] = nxt
            i += 2
        elif a in ("--清空", "--clear"):
            opts["清空"] = True
            i += 1
        elif a in ("--券", "--coupon"):
            # 可重复传：--券 "满减,300,50" --券 "折扣,0.9"
            if not isinstance(opts.get("券"), list):
                opts["券"] = []
            opts["券"].append(nxt)
            i += 2
        elif a in ("--plus", "--会员"):
            opts["plus"] = True
            i += 1
        elif a in ("--名", "--name"):
            opts["名"] = nxt
            i += 2
        elif a in ("--方案", "--plan"):
            # 比价用：--方案 "京东|399|满减,300,50;折扣,0.9"
            if not isinstance(opts.get("方案"), list):
                opts["方案"] = []
            opts["方案"].append(nxt)
            i += 2
        elif a in ("--图片", "--image", "-i"):
            opts["图片"] = nxt
            i += 2
        elif a in ("--截图", "--shot"):
            # 外卖比价用：--截图 "美团=D:\\a.png"
            if not isinstance(opts.get("截图"), list):
                opts["截图"] = []
            opts["截图"].append(nxt)
            i += 2
        elif not a.startswith("-"):
            # 裸参数，例如「python run.py 商品 D:\shot.png」里的路径。
            # 早先版本直接丢掉，导致商品命令收不到文件路径。
            opts.setdefault("_args", []).append(a)
            i += 1
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


def cmd_auto(opts: dict | None = None) -> int:
    """定时任务用的静默模式：抓一遍 → 刷新网页 → 写一条日志。

    两个刻意的设计，都是踩坑补的：

    1. **抓到 0 条时不覆盖已有页面。** 第三方免费接口偶尔抽风是常态
       （实测遇到过一次 HTTP 502）。如果那次就把页面写成「一张券都没有」，
       你打开看到的就是个空页面——比旧数据糟糕得多。所以没抓到就保留原样。
    2. **不写领取历史。** 每天自动跑一次，每次塞 50 条记录，
       用不了几天就把有用的记录挤没了。
    """
    from datetime import datetime

    from .config import PROJECT_ROOT
    from .store import data_dir
    from .webpage import render

    opts = opts or {}
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = data_dir() / "auto.log"

    def log(line: str) -> None:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{stamp}  {line}\n")
        except Exception:
            pass

    # 输出路径：
    #   · 没给 --输出 → 项目目录下的 out/优惠券.html（本机定时任务用这个）
    #   · 给了相对路径 → 按【当前工作目录】解析，不是项目目录。
    #     因为调用方（比如 CI）给相对路径时，预期就是相对它自己的 cwd。
    #     早先版本一律按项目目录解析，结果从别的目录跑就会写错地方。
    if opts.get("输出"):
        out_path = Path(opts["输出"])
        if not out_path.is_absolute():
            out_path = Path.cwd() / out_path
    else:
        out_path = PROJECT_ROOT / "out" / "优惠券.html"

    try:
        result = fetch_all(_auto_sources(), only=opts.get("源"))
        coupons = dedupe(rank(result.coupons))

        for e in result.errors:
            log(f"  数据源报错：{e}")

        if not coupons:
            kept = "保留原页面" if out_path.exists() else "目标文件不存在，无法兜底"
            log(f"本次抓到 0 条，{kept}")
            for n in result.notes:
                log(f"  提示：{n}")
            # 保留旧页面时返回 0（这不是错误，是「本次没更新」）；
            # 连兜底文件都没有才返回 1，让调用方知道真的没东西可用
            return 0 if out_path.exists() else 1

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render(coupons, result), encoding="utf-8")
        log(f"成功：抓到 {len(coupons)} 条，已写入 {out_path}")

        # 顺便跑一遍关注清单，把命中的记进日志——这是「全自动」的关键一环：
        # 你不需要主动查，跑完就知道有没有到目标价的
        try:
            from . import watch

            if watch.load():
                hits = [r for r in watch.check_all(coupons) if r.hit]
                if hits:
                    for h in hits:
                        log(f"🔔 达到目标价：{h.summary()}")
                else:
                    log("关注清单：暂无达到目标价的")
        except Exception as e:
            log(f"关注清单检查失败：{type(e).__name__}: {e}")
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


def cmd_mcd(opts: dict) -> int:
    """麦当劳官方 MCP 的诊断工具。

    为什么单独做一个命令：这个源需要 Token，我没法替你测。
    所以给你一个「一键把服务端原话打出来」的工具——
    跑完把输出发我，我就能照着真实结构把解析改对。
    """
    import os

    from .config import load_config
    from .mcp_client import McpClient, McpError, tool_result_json, tool_result_text

    print()
    token = (opts.get("令牌") or "").strip()
    if not token:
        for s in load_config().get("sources", []):
            if s.get("type") == "mcd_mcp":
                token = (s.get("token") or "").strip()
                break
    if not token:
        token = (os.environ.get("MCD_MCP_TOKEN") or "").strip()

    if not token:
        print("  ⚠️ 还没配置麦当劳 MCP Token。")
        print()
        print("  这个源是麦当劳中国自己开放的官方接口，Token 免费：")
        print("    1. 打开 https://open.mcd.cn/mcp")
        print("    2. 右上角登录（手机号验证码）")
        print("    3. 点「控制台」→「激活」→ 同意协议 → 复制 Token")
        print('    4. 填进 config.json 里 mcd_official 那条的 "token"')
        print()
        print("  填好后运行：python run.py 麦当劳        看能领到什么券")
        print("             python run.py 麦当劳 --工具   列出全部 24 个工具")
        print()
        return 1

    client = McpClient(token=token)
    print("  1) 握手……")
    try:
        info = client.initialize()
    except McpError as e:
        print(f"     ❌ {e.message}")
        print()
        return 1
    srv = (info or {}).get("serverInfo", {}) or {}
    print(f"     ✅ 连上了：{srv.get('name', '?')} v{srv.get('version', '?')}")
    if client.session_id:
        print(f"     会话 ID：{client.session_id[:16]}…")

    print()
    print("  2) 列出工具……")
    try:
        tools = client.list_tools()
    except McpError as e:
        print(f"     ❌ {e.message}")
        return 1
    names = [t.get("name") for t in tools if isinstance(t, dict)]
    print(f"     共 {len(names)} 个：{', '.join(names[:12])}{' …' if len(names) > 12 else ''}")

    if opts.get("工具"):
        print()
        print("  完整的工具清单：")
        for t in tools:
            if isinstance(t, dict):
                print(f"     · {t.get('name')}  {(t.get('description') or '')[:60]}")
        print()
        return 0

    tool = opts.get("调用") or "available-coupons"
    print()
    print(f"  3) 调用 {tool}……")
    try:
        raw = client.call_tool(tool, {})
    except McpError as e:
        print(f"     ❌ {e.message}")
        return 1

    text = tool_result_text(raw)
    parsed = tool_result_json(raw)
    print(f"     原始返回长度：{len(text)} 字符")
    print()
    print("  ── 服务端原始返回（前 1500 字符）──")
    print("  " + (text[:1500] or "(空)").replace("\n", "\n  "))
    print("  ── 结束 ──")
    if parsed is not None:
        import json as _json

        print()
        print("  解析出的 JSON 结构（前 800 字符）：")
        print("  " + _json.dumps(parsed, ensure_ascii=False, indent=1)[:800].replace("\n", "\n  "))
    print()
    print("  如果「优惠券」没显示出来，把上面这段原始返回发我，我照着改解析。")
    print()
    return 0



def _read_coupons_interactive() -> list:
    """交互式让用户逐张录券，空行结束。"""
    from .stack_cli import SpecError, parse_coupon

    print("  逐张输入券，直接回车结束。格式：")
    print("      满减,300,50      → 满 300 减 50")
    print("      折扣,0.9         → 9 折券（写「付多少比例」，9 折就写 0.9）")
    print("      无门槛,20        → 直接减 20")
    print("      补贴,0.15        → 按 15% 补贴（国补）")
    print("      会员,500,30      → 会员满减（需要 Plus）")
    print("      想指定互斥组就在后面再加一段：满减,300,50,店铺券")
    print()
    coupons = []
    while True:
        try:
            raw = input(f"  第 {len(coupons) + 1} 张（回车结束）：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            break
        try:
            c = parse_coupon(raw)
            coupons.append(c)
            print(f"      ✓ 已添加：{c.name}")
        except SpecError as e:
            print(f"      ✗ {e}")
    return coupons


def cmd_stack(opts: dict) -> int:
    """叠券计算器：算「叠完所有券之后实际付多少」。"""
    from .stack_cli import (
        SpecError, best, parse_coupon_list, render_result, render_topup,
        resolve_platform, suggest_topup,
    )

    print()

    price = opts.get("价")
    specs = opts.get("券") or []

    if price is None:
        try:
            raw = input("  商品标价：").strip().lstrip("¥￥")
            price = float(raw)
        except (ValueError, EOFError, KeyboardInterrupt):
            print("  没填价格，已取消。")
            return 1

    platform = resolve_platform(opts.get("平台") or "")
    if not opts.get("平台"):
        try:
            raw = input(f"  平台（京东/拼多多/淘宝/通用，回车={platform}）：").strip()
            if raw:
                platform = resolve_platform(raw)
        except (EOFError, KeyboardInterrupt):
            print()

    has = set()
    if opts.get("plus"):
        has.add("plus")
    elif not specs:
        try:
            raw = input("  你是京东 Plus 会员吗？(y/N)：").strip().lower()
            if raw in ("y", "yes", "是", "有"):
                has.add("plus")
        except (EOFError, KeyboardInterrupt):
            print()

    if specs:
        try:
            coupons = parse_coupon_list(specs)
        except SpecError as e:
            print(f"  ✗ {e}")
            return 1
    else:
        print()
        coupons = _read_coupons_interactive()

    if not coupons:
        print()
        print("  没有券，那实付就是标价本身。")
        print()
        return 0

    res = best(price, coupons, platform, has)
    print()
    print("  " + "─" * 58)
    print(render_result(res))
    tips = suggest_topup(price, coupons, has)
    if tips:
        print(render_topup(tips))
    print()
    return 0


def _parse_plan(spec: str):
    """解析 "京东|399|满减,300,50;折扣,0.9" 这种一行描述。"""
    from .stack_cli import SpecError, parse_coupon_list, resolve_platform

    parts = str(spec).split("|")
    if len(parts) < 2:
        raise SpecError(f"「{spec}」格式不对，应该是 平台|标价|券1;券2")
    platform = resolve_platform(parts[0])
    try:
        price = float(parts[1])
    except ValueError as e:
        raise SpecError(f"「{parts[1]}」不是有效价格") from e
    specs = [x for x in (parts[2].split(";") if len(parts) > 2 else []) if x.strip()]
    return platform, price, parse_coupon_list(specs)


def cmd_compare(opts: dict) -> int:
    """比价：同一件商品在几个平台的到手价对比。

    说清楚它做什么、不做什么：
      做的是「你知道各平台标价，帮你算叠完券之后哪个最便宜」。
      **不做**「自动去淘宝/京东/拼多多搜出同一件商品再比」——那需要抓平台页面
      或者拿到所有平台的商品接口，前者不可靠、违反平台规则，后者拿不到。
      而且同一件商品在不同平台标题和 ID 完全不同，自动匹配本身就是个难题。
    """
    from .stack_cli import SpecError, best, render_result, resolve_platform

    print()

    plans = opts.get("方案") or []

    if not plans:
        # 交互式：逐行录「平台|标价|券」
        name = ""
        try:
            name = input("  商品名（可留空）：").strip()
        except (EOFError, KeyboardInterrupt):
            pass
        print()
        print("  逐个平台录一行，格式：平台|标价|券1;券2")
        print("  例如：京东|399|满减,300,50;折扣,0.9")
        print("  没有券就只写「拼多多|359」。直接回车结束。")
        print()
        while True:
            try:
                raw = input(f"  第 {len(plans) + 1} 个平台（回车结束）：").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not raw:
                break
            plans.append(raw)
        if name:
            opts["名"] = name

    if len(plans) < 2:
        print()
        print("  至少要录两个平台才能比。")
        print()
        return 1

    results = []
    for spec in plans:
        try:
            platform, price, coupons = _parse_plan(spec)
        except SpecError as e:
            print(f"  ✗ {e}")
            return 1
        has = {"plus"} if opts.get("plus") else set()
        results.append((platform, price, best(price, coupons, platform, has)))

    # 按到手价排序
    results.sort(key=lambda x: x[2].final_price)

    name = opts.get("名") or "这件商品"
    print()
    print("  " + "═" * 58)
    print(f"  {name} · 各平台到手价对比")
    print("  " + "═" * 58)
    print()
    print("    排名  平台           标价        到手价      省")
    print("    " + "─" * 52)
    for i, (platform, price, res) in enumerate(results, 1):
        mark = " ←最便宜" if i == 1 else ""
        print(f"     {i}    {platform:<12} {price:>9.2f}  {res.final_price:>10.2f}"
              f"  {res.total_saved:>7.2f}{mark}")

    if len(results) >= 2:
        gap = results[-1][2].final_price - results[0][2].final_price
        print()
        if gap > 0.01:
            print(f"    最便宜比最贵省 {gap:.2f} 元（{gap / results[-1][2].final_price * 100:.1f}%）")
        else:
            print("    几个平台到手价一样。")

    print()
    print("  " + "─" * 58)
    for platform, price, res in results:
        print()
        print(render_result(res, title=f"{platform}（标价 {price:.2f}）"))
    print()
    print("  ⚠️ 以上都按各平台的公开叠加顺序估算，**以下单页结算时为准**。")
    print("     券的可用性受账号资质、地区、时段影响，实际可能用不上。")
    print()
    return 0



def _ask_float(prompt: str, default: float = 0.0) -> float:
    """问一个数字，空输入就用默认值。"""
    try:
        raw = input(prompt).strip().lstrip("¥￥")
    except (EOFError, KeyboardInterrupt):
        return default
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"      「{raw}」不是数字，按 {default:g} 算")
        return default


def _parse_discount_list(raw: str, group: str) -> list:
    """解析 "40,8;60,15" 这种满减列表。"""
    from .stacking import Coupon

    out = []
    for seg in str(raw).split(";"):
        seg = seg.strip()
        if not seg:
            continue
        nums = [x.strip() for x in seg.replace("减", ",").replace("-", ",").split(",") if x.strip()]
        try:
            if len(nums) >= 2:
                thr, val = float(nums[0]), float(nums[1])
                out.append(Coupon(f"满{thr:g}减{val:g}", "满减", thr, val, group))
            elif len(nums) == 1:
                val = float(nums[0])
                out.append(Coupon(f"减{val:g}", "无门槛", 0, val, group))
        except ValueError:
            print(f"      「{seg}」看不懂，已跳过")
    return out


def _read_pasted_block() -> str:
    """读用户粘贴的多行文本，直到一个空行结束。"""
    lines = []
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break
        if not line.strip():
            break
        # 用户可能在提示符后面直接粘，第一行会带上前面的提示残留，无妨
        lines.append(line)
    return "\n".join(lines)


def _ask_platform_offer(platform: str):
    """交互式问一个平台的数字，返回 Offer 或 None（跳过）。

    先让用户粘结账页文本（能自动认数字，省得一个个敲），
    认出来的值作为默认值，用户确认或改写。
    """
    from .delivery import Offer, parse_checkout_text

    print()
    print(f"  ── {platform} ──")
    print("     三种填法，任选：")
    print("       · 直接粘结账页文本（多行，敲空行结束）")
    print("       · 输入截图路径，我用系统 OCR 读（例如 C:\\shot.png）")
    print("       · 直接回车，逐项手填")
    # 注意：提示符那一行读进来的内容不能丢——它往往正是「商品小计」那一行。
    # 早先版本 `input("      > ")` 直接丢掉返回值，结果粘贴的第一行永远被吞掉。
    try:
        first = input("      > ")
    except (EOFError, KeyboardInterrupt):
        first = ""
    rest = _read_pasted_block()
    pasted = first + "\n" + rest if first.strip() else rest

    # 如果用户给的是一个存在的图片文件，走 OCR
    pre = {}
    if pasted.strip() and len(pasted.splitlines()) == 1:
        maybe = pasted.strip().strip('"').strip("'")
        from pathlib import Path as _P

        if _P(maybe).suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".webp") and _P(maybe).exists():
            from .receipt import OcrError, ocr_image, parse_receipt

            print(f"      正在识别截图：{maybe}")
            try:
                ocr_text = ocr_image(maybe)
                pre = parse_receipt(ocr_text)
                print("      OCR 读到：")
                for ln in ocr_text.splitlines()[:10]:
                    print(f"        {ln}")
            except OcrError as e:
                print(f"      ✗ {e}")

    if not pre and pasted.strip():
        pre = parse_checkout_text(pasted)
    if pre:
        bits = []
        label_map = [
            ("items", "菜品"), ("delivery", "配送"), ("packing", "打包"),
            ("shop_discount", "店铺满减"), ("coupon", "平台券"),
            ("red_packet", "红包"), ("final", "实付"),
        ]
        for k, name in label_map:
            if k in pre:
                bits.append(f"{name} {pre[k]:g}")
        if pre.get("member"):
            bits.append("会员")
        print(f"      ✓ 认到：{' | '.join(bits)}")
        print("        下面每项的回车值就是它，不对就直接改。")
    elif pasted.strip():
        print("      （没认出数字，逐项填吧）")

    def d(key, fallback):
        return pre.get(key, fallback)

    items = _ask_float("      菜品小计（优惠前）：", d("items", -1))
    if items < 0:
        print("      跳过这个平台")
        return None
    if items == 0:
        print("      菜品是 0，跳过这个平台")
        return None

    delivery = _ask_float("      配送费：", d("delivery", 0.0))
    packing = _ask_float("      打包费：", d("packing", 0.0))

    shop_default = f"{pre['items']:g},{pre['shop_discount']:g}" if pre.get("shop_discount") else ""
    try:
        raw = input(f"      门店满减（如 40,8；多张分号；没有回车）"
                    f"{'[' + shop_default + '] ' if shop_default else ''}：").strip()
    except (EOFError, KeyboardInterrupt):
        raw = ""
    if not raw and shop_default:
        raw = shop_default
    shop = _parse_discount_list(raw, "店铺券")

    coupon_default = f"{pre['items']:g},{pre['coupon']:g}" if pre.get("coupon") else ""
    try:
        raw = input(f"      平台券（门槛,面额；多张分号；没有回车）"
                    f"{'[' + coupon_default + '] ' if coupon_default else ''}：").strip()
    except (EOFError, KeyboardInterrupt):
        raw = ""
    if not raw and coupon_default:
        raw = coupon_default
    coupons = _parse_discount_list(raw, "平台券")

    red = _ask_float("      红包（直接减多少，没有填 0）：", d("red_packet", 0.0))

    member = bool(pre.get("member"))
    free_delivery = False
    try:
        dft = "Y/n" if member else "y/N"
        ans = input(f"      有会员吗？({dft})：").strip().lower()
        if ans in ("y", "yes", "是", "有"):
            member = True
        elif ans in ("n", "no", "否", "没有"):
            member = False
        if member:
            ans2 = input("        会员免配送费吗？(y/N)：").strip().lower()
            free_delivery = ans2 in ("y", "yes", "是", "有")
    except (EOFError, KeyboardInterrupt):
        pass

    return Offer(platform, items, delivery, packing, shop, coupons, red,
                 member=member, member_delivery_free=free_delivery,
                 expected_final=pre.get('final'))


def _parse_offer_spec(spec: str):
    """解析 "美团|45|3|1|40,8;60,15|50,6|5|n" 这种一行描述。"""
    from .delivery import Offer

    parts = [x.strip() for x in str(spec).split("|")]
    if len(parts) < 2:
        raise ValueError(f"「{spec}」格式不对，至少要有 平台|菜品小计")

    def num(i, default=0.0):
        if i >= len(parts) or not parts[i]:
            return default
        return float(parts[i])

    shop = _parse_discount_list(parts[4], "店铺券") if len(parts) > 4 else []
    coupons = _parse_discount_list(parts[5], "平台券") if len(parts) > 5 else []
    red = num(6)
    member = len(parts) > 7 and parts[7].lower() in ("y", "yes", "会员", "1")
    return Offer(parts[0], float(parts[1]), num(2), num(3), shop, coupons, red,
                 member=member, member_delivery_free=member)


def cmd_delivery(opts: dict) -> int:
    """外卖比价：同一家店在美团/淘宝闪购/京东外卖，算上券和配送费谁最便宜。

    说清楚它做什么、不做什么：
      做的是「你照着各平台结账页把数字填进来，算完券和配送费之后哪个真便宜」。
      **不做**「自动去各平台抓菜品价格」——实测过，三个平台的页面都是纯 JS
      渲染的应用外壳，HTML 里没有任何菜单或价格，而且都要登录。抓不到。
    """
    from .delivery import Offer, compare, parse_share_text, render_comparison

    print()

    shop = opts.get("名") or ""
    specs = opts.get("方案") or []
    shots = opts.get("截图") or []

    from .receipt import describe as describe_receipt

    if shots:
        # 一次性模式：--截图 "美团=D:\a.png" --截图 "淘宝闪购=D:\b.png"
        from .receipt import OcrError, ocr_image, parse_receipt
        from .stack_cli import SpecError, parse_coupon_list

        offers = []
        for spec in shots:
            if "=" not in spec:
                print(f"  ✗ 「{spec}」格式不对，应该是 平台=图片路径")
                return 1
            platform, path = spec.split("=", 1)
            platform, path = platform.strip(), path.strip().strip('"').strip("'")
            print(f"  识别 {platform}：{path}")
            try:
                text = ocr_image(path)
            except OcrError as e:
                print(f"    ✗ {e}")
                continue

            pre = parse_receipt(text)
            print(f"    {describe_receipt(pre)}")
            if "items" not in pre:
                print("    ✗ 没认出菜品小计，跳过这个平台")
                continue

            # 抓到的券不参与计算（面额是从标题猜的），只用用户明确录入的
            shop_coupons = []
            if pre.get("shop_discount"):
                shop_coupons.append(
                    f"满减,{pre['items']:g},{pre['shop_discount']:g}"
                )
            plat_coupons = []
            if pre.get("coupon"):
                plat_coupons.append(f"满减,{pre['items']:g},{pre['coupon']:g}")

            from .delivery import Offer

            offers.append(Offer(
                platform=platform,
                items=pre["items"],
                delivery=pre.get("delivery", 0.0),
                packing=pre.get("packing", 0.0),
                shop_discounts=parse_coupon_list(shop_coupons),
                coupons=parse_coupon_list(plat_coupons),
                red_packet=pre.get("red_packet", 0.0),
                member=bool(pre.get("member")),
                member_delivery_free=bool(pre.get("member")),
                expected_final=pre.get("final"),
            ))
        print()

    elif not specs:
        print("  逐个平台填数字。填几个比几个，一个都不填就退出。")
        print("  每个平台都可以：粘结账页文本 / 给截图路径 / 直接手填。")
        print()
        offers = []
        for platform in ("美团", "淘宝闪购(饿了么)", "京东外卖"):
            o = _ask_platform_offer(platform)
            if o:
                offers.append(o)
                # 店名等第一个平台填完再问，避免「第一问就卡住」
                if not shop:
                    try:
                        raw = input("      这家店叫什么？（可回车跳过）：").strip()
                    except (EOFError, KeyboardInterrupt):
                        raw = ""
                    if raw:
                        shop, _url = parse_share_text(raw)
                        if not shop:
                            shop = raw

        if offers:
            print()
            try:
                raw = input("  要不要现在就算？(Y/n)：").strip().lower()
            except (EOFError, KeyboardInterrupt):
                raw = "y"
            if raw in ("n", "no", "否", "不"):
                print()
                return 0
    else:
        offers = []
        for spec in specs:
            try:
                offers.append(_parse_offer_spec(spec))
            except ValueError as e:
                print(f"  ✗ {e}")
                return 1
        shop = opts.get("名") or ""

    if len(offers) < 1:
        print()
        print("  一个平台都没填，没法比。")
        print()
        return 1

    if len(offers) == 1:
        print()
        print("  只填了一个平台，没法横向比，但可以给你算到手价：")

    results = compare(offers)

    # 给每个平台生成「怎么点出来」的操作步骤——这是用户要的核心：
    # 不代下单，但要告诉他怎么操作最省。
    from .advice import build_advice, render_comparison as render_advice
    from .stack_cli import SpecError, parse_coupon
    from .stacking import best as _best

    advices = []
    for offer, res in zip(offers, results):
        # 重新算一遍以拿到 stacking.Result（含 confidence、order_matters 等）
        try:
            coupons_obj = list(offer.all_coupons())
            sr = _best(offer.items, coupons_obj, "外卖",
                       has={"plus"} if offer.member else set(),
                       threshold_base="base")
        except Exception:
            continue
        advices.append(build_advice(
            offer.platform, sr, coupons_obj,
            has_member=offer.member,
        ))

    print()
    print(render_comparison(results, shop))
    if advices:
        print(render_advice(advices))
    print()
    return 0



def cmd_watch(opts: dict) -> int:
    """关注清单：录一次，之后每次搜券/定时任务都自动帮你算和提醒。"""
    from . import watch

    print()

    if opts.get("清空"):
        watch.clear()
        print("  清单已清空。")
        print()
        return 0

    if opts.get("删除"):
        ok = watch.remove(opts["删除"])
        print("  已删除。" if ok else f"  没找到「{opts['删除']}」。")
        print()
        return 0

    # 新增
    name = opts.get("名")
    if name:
        from .watch import WatchItem

        prices = {}
        raw_prices = opts.get("价") or ""
        for seg in str(raw_prices).split(","):
            seg = seg.strip()
            if not seg:
                continue
            if "=" in seg:
                plat, val = seg.split("=", 1)
            elif ":" in seg:
                plat, val = seg.split(":", 1)
            else:
                print(f"  ✗ 「{seg}」格式不对，应该是 平台=价格")
                return 1
            try:
                prices[plat.strip()] = float(val.strip())
            except ValueError:
                print(f"  ✗ 「{val}」不是价格")
                return 1

        item = WatchItem(
            name=name,
            kind=opts.get("类型") or "商品",
            target=opts.get("目标"),
            note=opts.get("备注") or "",
            prices=prices,
        )
        watch.add(item)
        print(f"  已加入关注清单：{name}")
        for plat, val in prices.items():
            print(f"    {plat}: {val:.2f}")
        if item.target is not None:
            print(f"    目标价：{item.target:.2f}（低于它就提醒）")
        print()
        return 0

    # 只检查：先抓一遍最新券，再匹配到清单上
    from .config import load_config
    from .rank import dedupe, rank
    from .sources import fetch_all

    sources = load_config().get("sources") or []
    print("  正在抓最新券……")
    try:
        fetched = dedupe(rank(fetch_all(sources).coupons))
        print(f"  拿到 {len(fetched)} 条券，开始匹配。")
    except Exception as e:
        fetched = []
        print(f"  抓券失败（{type(e).__name__}），只用你录的券来算。")

    results = watch.check_all(fetched)
    print(watch.render_report(results))
    return 0



def cmd_product(opts: dict) -> int:
    """商品页识别：一张截图 → 这单多少钱 + 能用什么券 + 还差什么。

    设计意图：用户最常见的动作是在外卖 App 里看到某个商品，
    截一张商品页就发过来。那就用**一张图**给出这一单的结论，
    而不是逼他截三张、走完整比价流程。

    跨平台比价仍然需要另外两家的价格——这一点会在输出里写明，
    不假装一张图能算出三家。
    """
    from .product import describe_product, parse_product_page
    from .receipt import OcrError, ocr_image

    print()

    args = opts.get("_args") or []
    path = opts.get("图片") or (args[0] if args else None) or opts.get("名")
    if not path:
        print("  用法：python run.py 商品 <截图路径>")
        print("  例如：python run.py 商品 D:\\shot.png")
        print()
        return 1

    path = str(path).strip().strip('"').strip("'")

    print(f"  识别：{path}")
    try:
        text = ocr_image(path)
    except OcrError as e:
        print(f"  ✗ {e}")
        print()
        return 1

    info = parse_product_page(text)
    print()
    print("  " + "─" * 56)
    print(f"  {describe_product(info)}")
    print("  " + "─" * 56)

    price = info.get("price")
    if price is None:
        print()
        print("  没读出价格，没法算。可以换一张更清晰的截图（只截价格那一块就够）。")
        print()
        return 1

    # 在已抓到的券里找商家/品牌相关的
    from .config import load_config
    from .rank import dedupe, rank
    from .sources import fetch_all

    print()
    print("  正在找这个商家能用的券……")
    try:
        coupons = dedupe(rank(fetch_all(load_config().get("sources") or []).coupons))
    except Exception as e:
        coupons = []
        print(f"  （抓券失败：{type(e).__name__}）")

    merchant = (info.get("merchant") or "").strip()
    product = (info.get("product") or "").strip()

    hits = []
    if merchant or product:
        for c in coupons:
            t = c.title
            if (merchant and merchant in t) or (product and product[:6] in t) or \
               (merchant and any(k in t for k in (merchant[:2],)) and len(merchant) >= 2):
                hits.append(c)

    # 平台级通用券也算「能用」，但要说清楚不是这家的专属券
    generic = [c for c in coupons if c not in hits and c.tag in ("口令券", "官方券", "领券入口")]

    print()
    if hits:
        print(f"  ✅ 找到 {len(hits)} 张和「{merchant or product}」相关的券：")
        for c in hits:
            print(f"     · [{c.platform}] {c.title}")
    else:
        print(f"  ❌ 没有找到「{merchant or product}」的专属券。")
        print()
        print("     说明：商家专属券（店铺券）只在 App 里、由商家自己发，")
        print("     走的是商家侧接口，没有公开渠道能批量拿到。")
        print("     GitHub 上也没有现成方案（查过，唯一沾边的是微信支付商家券，")
        print("     跟外卖无关）。")

    if generic:
        print()
        print(f"  另外这些平台通用券可能能用（不是这家专属，是平台发的）：")
        for c in generic[:6]:
            print(f"     · [{c.platform}] {c.title[:40]}")
        if len(generic) > 6:
            print(f"     ……还有 {len(generic) - 6} 张，运行「python run.py 搜券 --平台 {generic[0].platform}」看全部")

    # 算这一单
    print()
    print("  " + "─" * 56)
    print(f"  这个商品现在标价 {price:g}")
    if info.get("original"):
        print(f"  原价 {info['original']:g}，平台已经降了 {info['original'] - price:g}")
    print()
    print("  平台上的「一口价 / 立省」通常已经是它给的最低价了。")
    print("  想再省，只能看有没有**平台券**能叠在上面——去对应 App 的")
    print("  「我的 → 优惠券」里看有没有能用的红包。")
    print()
    print("  " + "─" * 56)
    print("  ⚠️ 关于跨平台比价：")
    print("    同一道菜在美团/饿了么/京东的价格不一样，但**只有你能看到**")
    print("    （平台不开放菜单接口，实测过）。所以想比价，还是得在另外")
    print("    两家搜一下这个店名，把价格告诉我，或者用「外卖比价」传截图。")
    print()

    if info.get("suspicious"):
        print("  ⚠️ 识别过程中有读不准的地方，上面已经标出来了。")
        print("     价格那一项如果也不确定，建议手动核对一下。")
        print()

    return 0


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
        "14": ("麦当劳官方券诊断", lambda: cmd_mcd(_default_opts())),
        "15": ("叠券算账（叠完之后实付多少）", lambda: cmd_stack(_default_opts())),
        "16": ("多平台比价（哪个最便宜）", lambda: cmd_compare(_default_opts())),
        "17": ("外卖比价（同一家店哪个平台便宜）", lambda: cmd_delivery(_default_opts())),
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
        for key in ("9", "10", "11", "12", "13", "14", "15", "16", "17"):
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
        "令牌": None, "工具": False, "调用": None,
        "价": None, "券": [], "plus": False, "名": None, "方案": None,
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
    "麦当劳": "mcd", "mcd": "mcd", "麦当劳诊断": "mcd",
    "叠券": "stack", "凑单": "stack", "实付": "stack", "stack": "stack",
    "外卖比价": "delivery", "外卖": "delivery", "点外卖": "delivery", "delivery": "delivery",
    "关注": "watch", "关注清单": "watch", "监控": "watch", "watch": "watch",
    "商品": "product", "识图": "product", "product": "product",
    "比价": "compare", "compare": "compare",
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
        return cmd_auto(opts)
    if cmd == "schedule":
        return cmd_schedule(opts)
    if cmd == "shortcut":
        return cmd_shortcuts()
    if cmd == "serve":
        return cmd_serve(opts)
    if cmd == "mcd":
        return cmd_mcd(opts)
    if cmd == "stack":
        return cmd_stack(opts)
    if cmd == "compare":
        return cmd_compare(opts)
    if cmd == "delivery":
        return cmd_delivery(opts)
    if cmd == "watch":
        return cmd_watch(opts)
    if cmd == "product":
        return cmd_product(opts)
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
