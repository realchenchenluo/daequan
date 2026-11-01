"""
读系统剪贴板。零第三方依赖。

为什么要读剪贴板
────────────────────────────────────────────
配套的 `web/menu-sniffer.user.js` 跑在你自己的浏览器里，
把当前店铺页的菜单整理成文本后「复制」——复制到哪？剪贴板。
所以工具只需要读剪贴板，不需要联网、不需要监听端口、不需要你的 cookie。

这也是这个方案最关键的取舍：
**工具从来没有碰到你的登录态，它只碰到了一段文字。**

实现说明
────────────────────────────────────────────
Windows 用 PowerShell 的 Get-Clipboard。中文编码有两个坑，都踩过了：
  · 直接读 stdout，PowerShell 默认按 GBK 输出，UTF-8 解会乱码
  · 用 -Raw 可以保留换行，但编码还得指定
所以走的办法是：先让 PowerShell 把内容写成 UTF-8 临时文件，Python 再读文件。
多一步 IO，换来编码绝对可靠。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


class ClipboardError(Exception):
    """读不到剪贴板时抛这个，message 直接给用户看。"""


def _read_windows() -> str:
    tmp = Path(tempfile.gettempdir()) / "_dq_clipboard.txt"
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass

    # 用 UTF8 写文件，避免 stdout 的 GBK/UTF-8 编码之争
    ps = (
        "$ErrorActionPreference='Stop';"
        f"$t = Get-Clipboard -Raw;"
        f"if ($null -eq $t) {{ $t = '' }};"
        f"[IO.File]::WriteAllText('{tmp}', $t, [Text.UTF8Encoding]::new($false))"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            timeout=25,
        )
    except FileNotFoundError as e:
        raise ClipboardError(
            "找不到 powershell，没法读剪贴板。你可以把内容存成 txt，"
            "然后用「python run.py 粘贴 路径」读文件。"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise ClipboardError("读剪贴板超时了（PowerShell 没响应）。") from e

    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace")[:300]
        raise ClipboardError(f"读剪贴板失败：{err.strip() or '未知原因'}")

    try:
        return tmp.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as e:
        raise ClipboardError(f"读取剪贴板临时文件失败：{e}") from e
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _read_mac() -> str:
    try:
        r = subprocess.run(["pbpaste"], capture_output=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise ClipboardError(f"读剪贴板失败：{e}") from e
    return r.stdout.decode("utf-8", "replace")


def _read_linux() -> str:
    for cmd in (["xclip", "-selection", "clipboard", "-o"],
                ["xsel", "--clipboard", "--output"],
                ["wl-paste"]):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=15)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace")
    raise ClipboardError(
        "系统里没有 xclip / xsel / wl-paste，读不到剪贴板。\n"
        "  可以装一个：sudo apt install xclip\n"
        "  或者把内容存成 txt，然后「python run.py 粘贴 路径」。"
    )


def read_clipboard() -> str:
    """读系统剪贴板，返回文本。读不到抛 ClipboardError。"""
    if sys.platform == "win32":
        return _read_windows()
    if sys.platform == "darwin":
        return _read_mac()
    return _read_linux()


def read_source(arg: str = "") -> str:
    """按参数决定从哪读：给了路径就读文件，否则读剪贴板。"""
    if arg:
        p = Path(os.path.expanduser(str(arg).strip().strip('"').strip("'")))
        if not p.exists():
            raise ClipboardError(f"文件不存在：{p}")
        try:
            return p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Windows 记事本存的可能是 GBK
            return p.read_text(encoding="gbk", errors="replace")
        except OSError as e:
            raise ClipboardError(f"读文件失败：{e}") from e
    return read_clipboard()
