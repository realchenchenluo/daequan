#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优惠猎手 —— 主入口

用法：
    python run.py                # 抓一遍全部平台
    python run.py 登录            # 登录美团（发券力度最大）
    python run.py 领券            # 让美团把专属券发进账号
    python run.py 搜券 --网页      # 抓取并生成网页版
    python run.py 帮助            # 全部命令

Windows 用户直接双击「一键运行.bat」也行。
"""

import sys
from pathlib import Path

# 保证从任何目录执行都能 import 到本项目的包
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _fix_windows_console() -> None:
    """Windows 的 cmd 默认是 GBK，中文和 emoji 会乱码或直接报错。

    Python 3.7+ 的自带方法，比手动包一层 TextIOWrapper 更稳。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> int:
    _fix_windows_console()

    from coupon_hunter.cli import main as cli_main

    try:
        return cli_main()
    except KeyboardInterrupt:
        print("\n  已取消。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
