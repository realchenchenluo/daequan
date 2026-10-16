#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跑全部自检：python tests/run_all.py

零依赖，不用装 pytest。任何一个失败都会让退出码变成 1，
所以也能直接放进 CI 当守门用。
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    tests = sorted(HERE.glob("test_*.py"))
    if not tests:
        print("  没找到任何测试文件")
        return 1

    failed = []
    for t in tests:
        print(f"\n{'=' * 60}")
        print(f"  {t.name}")
        print("=" * 60)
        r = subprocess.run([sys.executable, str(t)], cwd=HERE.parent)
        if r.returncode != 0:
            failed.append(t.name)

    print()
    print("=" * 60)
    if failed:
        print(f"  有 {len(failed)} 个测试文件失败：{', '.join(failed)}")
    else:
        print(f"  ✓ 全部 {len(tests)} 个测试文件通过")
    print("=" * 60)
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
