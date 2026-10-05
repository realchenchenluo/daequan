"""终端输出的排版。目标是：一眼能看出哪张券最值得领。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from .models import Coupon
from .store import is_claimed_today

# 关掉颜色：设 NO_COLOR=1，或者在非 tty 环境自动关闭。
# 注意 sys.stdout 可能是 None —— 定时任务用 pythonw.exe 跑的时候就是这样，
# 直接调 sys.stdout.isatty() 会抛 AttributeError 把整个程序带崩。
def _supports_color() -> bool:
    try:
        if os.environ.get("NO_COLOR"):
            return False
        return bool(sys.stdout and sys.stdout.isatty())
    except Exception:
        return False


_USE_COLOR = _supports_color()

C_RESET = "\033[0m" if _USE_COLOR else ""
C_BOLD = "\033[1m" if _USE_COLOR else ""
C_DIM = "\033[2m" if _USE_COLOR else ""
C_RED = "\033[31m" if _USE_COLOR else ""
C_GREEN = "\033[32m" if _USE_COLOR else ""
C_YELLOW = "\033[33m" if _USE_COLOR else ""
C_CYAN = "\033[36m" if _USE_COLOR else ""

_TAG_COLOR = {
    "官方直发": C_GREEN,
    "口令券": C_CYAN,
    "会场": C_YELLOW,
    "扫码会场": C_YELLOW,
    "自定义源": C_DIM,
}


def width() -> int:
    try:
        return max(60, min(shutil.get_terminal_size().columns, 100))
    except Exception:
        return 80


def hr(char: str = "─") -> str:
    return char * width()


def copy_to_clipboard(text: str) -> bool:
    """把文本塞进系统剪贴板。失败返回 False（不算致命错误）。

    注意：这里刻意不用 shell=True。券码来自第三方接口，属于不可信输入，
    虽然它只会进 stdin 而不会进命令行，但少一个 shell 解析层就少一类风险。
    """
    if not text:
        return False
    try:
        if sys.platform == "win32":
            # clip 是 Windows 自带命令，配合 UTF-16LE 才能正确复制中文和 emoji
            p = subprocess.run(["clip"], input=text.encode("utf-16le"))
            return p.returncode == 0
        if sys.platform == "darwin":
            p = subprocess.run(["pbcopy"], input=text.encode("utf-8"))
            return p.returncode == 0
        p = subprocess.run(
            ["xclip", "-selection", "clipboard"], input=text.encode("utf-8")
        )
        return p.returncode == 0
    except Exception:
        return False


def print_header(title: str) -> None:
    print()
    print(f"{C_BOLD}{hr('═')}{C_RESET}")
    print(f"{C_BOLD}  {title}{C_RESET}")
    print(f"{C_BOLD}{hr('═')}{C_RESET}")


def print_coupons(coupons: list[Coupon], *, show_index: bool = True, top: int | None = None) -> None:
    if not coupons:
        print(f"{C_YELLOW}  这次一张券都没抓到。{C_RESET}")
        return

    shown = coupons[:top] if top else coupons

    for i, c in enumerate(shown, 1):
        tag_color = _TAG_COLOR.get(c.tag, "")
        head = f"{C_BOLD}{c.title}{C_RESET}"
        if show_index:
            head = f"{C_BOLD}{i:>2}.{C_RESET} {head}"

        print()
        print(f"  {head}")
        print(
            f"      {tag_color}[{c.tag}]{C_RESET} "
            f"{C_DIM}{c.platform} · {c.source}{C_RESET}   "
            f"{C_RED}{c.discount_text()}{C_RESET}"
        )

        if c.valid_to:
            print(f"      {C_DIM}有效期至 {c.valid_to}{C_RESET}")

        if c.code:
            print(f"      {C_GREEN}口令：{C_BOLD}{c.code}{C_RESET}")
        if c.url and not c.url.endswith((".jpg", ".png", ".jpeg")):
            print(f"      {C_CYAN}链接：{c.url}{C_RESET}")
        elif c.url:
            print(f"      {C_CYAN}二维码：{c.url}{C_RESET}")
        if c.guideline:
            print(f"      {C_DIM}{c.guideline}{C_RESET}")

    if top and len(coupons) > top:
        print()
        print(f"  {C_DIM}……还有 {len(coupons) - top} 条，加 --全部 查看{C_RESET}")


def print_footer(result, elapsed: float, shown: int | None = None) -> None:
    print()
    print(hr())
    if result.errors:
        print(f"{C_RED}  有 {len(result.errors)} 个源出问题了：{C_RESET}")
        for e in result.errors:
            print(f"    · {e}")
    for n in result.notes:
        print(f"{C_YELLOW}  · {n}{C_RESET}")
    total = len(result.coupons)
    if shown is not None and shown != total:
        print(f"{C_DIM}  符合条件 {shown} 条 / 共抓到 {total} 条，耗时 {elapsed:.1f} 秒{C_RESET}")
    else:
        print(f"{C_DIM}  共 {total} 条，耗时 {elapsed:.1f} 秒{C_RESET}")
    print()


def save_json(coupons: list[Coupon], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([c.to_dict() for c in coupons], f, ensure_ascii=False, indent=2)


def claimed_banner(platform: str) -> str:
    if is_claimed_today(platform):
        return f"{C_YELLOW}（今天已领过）{C_RESET}"
    return ""
