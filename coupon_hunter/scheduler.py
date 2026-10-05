"""
定时任务：让工具每天早上自动抓一次券，你开机就能看到。

设计原则：**只提供能力，不擅自注册**。
装定时任务会改动系统状态（在 Windows 任务计划程序里加一条），这种事必须由你主动
触发，所以这里只提供 install / status / uninstall 三个动作，代码里没有任何地方会
在导入或搜券时自动把任务装上。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .config import PROJECT_ROOT

TASK_NAME = "CouponHunter_Daily"


def _decode(raw: bytes) -> str:
    """schtasks 的中文输出用的是系统 OEM 编码，逐个尝试解码。"""
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True)
    return p.returncode, _decode(p.stdout or b"") + _decode(p.stderr or b"")


def _launcher() -> str:
    """组装任务要执行的命令行。

    优先用 pythonw.exe：它是无窗口版解释器，定时跑的时候不会闪一个黑框出来。
    找不到就退回 python.exe。
    """
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    if pyw.exists():
        py = pyw
    script = PROJECT_ROOT / "run.py"
    return f'"{py}" "{script}" auto'


def install(time_str: str = "09:00") -> int:
    if sys.platform != "win32":
        print()
        print("  当前系统不是 Windows，请用 crontab 手工添加，例如：")
        print(f"    0 9 * * * {_launcher()}")
        print()
        return 1

    code, out = _run(
        [
            "schtasks", "/Create",
            "/TN", TASK_NAME,
            "/TR", _launcher(),
            "/SC", "DAILY",
            "/ST", time_str,
            "/F",
        ]
    )

    print()
    if code == 0:
        print(f"  ✅ 定时任务已装好：每天 {time_str} 自动抓一次券并刷新网页。")
        print()
        print("  注意两点：")
        print("    · 任务只在「你已登录 Windows」时运行。如果那个点电脑关着或没登录，")
        print("      当天就不会跑——开机后你可以自己双击「一键运行.bat」补一次。")
        print("    · 抓完的网页在 out\\优惠券.html，桌面上如果建了快捷方式就直接点它。")
        print()
        print("  不想要了：python run.py 定时任务 --卸载")
    else:
        print("  ❌ 安装失败。系统返回：")
        print("  " + out.strip().replace("\n", "\n  "))
        print()
        print("  常见原因：权限不足。试试右键「以管理员身份运行」再执行一次。")
    print()
    return code


def status() -> int:
    if sys.platform != "win32":
        print("\n  非 Windows 系统，请用 crontab -l 查看。\n")
        return 0

    code, out = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"])
    print()
    if code == 0:
        print("  定时任务已安装：")
        for line in out.strip().splitlines():
            if line.strip():
                print("    " + line.strip())
    else:
        print("  定时任务未安装。")
        print("  想装的话运行：python run.py 定时任务 --安装")
    print()
    return 0


def uninstall() -> int:
    if sys.platform != "win32":
        print("\n  非 Windows 系统，请用 crontab -e 手工删除。\n")
        return 1

    code, out = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    print()
    if code == 0:
        print("  ✅ 定时任务已删除，工具不会再自动运行。")
    else:
        print("  没找到这个任务，或者删除失败：")
        print("  " + out.strip().replace("\n", "\n  "))
    print()
    return code


# ──────────────────────────────────────────────────────────
# 桌面快捷方式
# ──────────────────────────────────────────────────────────

def make_shortcuts(dest: Path | None = None) -> int:
    """在桌面创建两个快捷方式：一个开菜单，一个直接看今天的券。

    dest 只在测试时传入（指到临时目录），正常用就是桌面。
    """
    if sys.platform != "win32":
        print("\n  这个功能目前只做了 Windows 版本。\n")
        return 1

    desktop = dest or (Path.home() / "Desktop")
    if not desktop.exists():
        print(f"\n  目标目录不存在：{desktop}\n")
        return 1

    page = PROJECT_ROOT / "out" / "优惠券.html"
    menu = PROJECT_ROOT / "一键运行.bat"

    # 路径里的单引号会让 PowerShell 字符串断掉，先挡掉
    for p in (desktop, PROJECT_ROOT):
        if "'" in str(p):
            print("\n  路径里有单引号，暂不支持，请手动创建快捷方式。\n")
            return 1

    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$s1 = $ws.CreateShortcut('{desktop}\\优惠猎手.lnk')
$s1.TargetPath = '{menu}'
$s1.WorkingDirectory = '{PROJECT_ROOT}'
$s1.Description = '打开优惠猎手菜单'
$s1.Save()
if (Test-Path '{page}') {{
  $s2 = $ws.CreateShortcut('{desktop}\\今日优惠券.lnk')
  $s2.TargetPath = '{page}'
  $s2.Description = '查看今天抓到的优惠券'
  $s2.Save()
}}
"""
    p = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True,
    )
    print()
    if p.returncode == 0:
        made = [f for f in desktop.glob("*.lnk") if f.name in ("优惠猎手.lnk", "今日优惠券.lnk")]
        print(f"  ✅ 已创建快捷方式（{desktop}）：")
        for f in made:
            print(f"     · {f.name}")
        if page.exists() and len(made) < 2:
            print("     （「今日优惠券」要等第一次生成网页后才会有）")
    else:
        print("  ❌ 创建失败：")
        print("  " + _decode(p.stderr or b"").strip())
    print()
    return p.returncode
