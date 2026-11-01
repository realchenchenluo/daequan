#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「这一页是被拦住了，还是正常页面」的判断自检。跑法：python tests/test_browser.py

这个判断错了后果很直接：
  · 正常登录页被判成滑块验证 → 用户去拖一个根本不存在的滑块，永远过不去
  · 滑块页被判成登录墙 → 用户以为登一下就好，实际上要手动拖

所以下面每一条都对应用户肉眼能看到的真实页面文字。
滑块/登录这些判断不需要联网、不需要浏览器，纯字符串分类，所以能这么单测。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.browser import classify, search_url  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


# 2026-10 真实读到的美团登录页（搜商家被 302 到这页）
MEITUAN_LOGIN = "美团外卖 发送验证码 登录 我已阅读并同意《美团用户协议》、《隐私政策》"


@case("美团短信登录页：判成「要登录」，不是滑块")
def _():
    login, captcha = classify("登录", MEITUAN_LOGIN)
    assert login is True, "应该判成要登录"
    assert captcha is False, "「发送验证码」不是滑块验证，误判了"
    return "login=True captcha=False"


@case("饿了么登录页：判成「要登录」")
def _():
    login, captcha = classify(
        "淘宝闪购-登录", "手机号登录 验证码登录 密码登录 获取验证码"
    )
    assert login is True and captcha is False
    return "login=True captcha=False"


@case("真滑块验证：判成「验证码」，不是登录墙")
def _():
    login, captcha = classify("安全验证", "为保障账号安全，请拖动滑块完成验证")
    assert captcha is True, "应该判成滑块"
    assert login is False, "有滑块时不该报成登录墙"
    return "captcha=True login=False"


@case("滑块页里同时写着登录：仍以滑块为准")
def _():
    login, captcha = classify("美团外卖", "登录 请按住左边滑块拖动到最右边")
    assert captcha is True
    assert login is False, "滑块优先，不能糊成登录墙"
    return "滑块优先于登录"


@case("正常的商家列表页：两个都不报")
def _():
    text = "高济百康药房（蒋台路分店）\n5.0分\n月售9999+\n起送 ¥20\n配送 约¥3.5"
    login, captcha = classify("美团外卖", text)
    assert login is False and captcha is False
    return "正常页面不误报"


@case("页脚出现「验证码」不影响判断")
def _():
    # 正文 1500 字之后才提到验证码，不该影响前面的判断
    text = "某店\n4.5分\n起送 ¥10\n" + ("占位" * 800) + "请勿泄露验证码"
    login, captcha = classify("美团外卖", text)
    assert captcha is False, "只看前 1500 字，页脚不该触发"
    return "长文本页脚不误判"


@case("搜索地址：关键词被 URL 编码")
def _():
    u = search_url("美团", "麦当劳 望京")
    assert "%E9%BA%A6%E5%BD%93%E5%8A%B3" in u, u
    assert " " not in u, u
    assert u.startswith("https://h5.waimai.meituan.com/"), u
    return u


@case("搜索地址：--网址 覆盖优先")
def _():
    u = search_url("美团", "麦当劳", "https://example.com/s?q={kw}")
    assert u == "https://example.com/s?q=%E9%BA%A6%E5%BD%93%E5%8A%B3", u
    return "自定义模板生效"


@case("搜索地址：没有 {kw} 时原样返回")
def _():
    u = search_url("美团", "麦当劳", "https://example.com/fixed")
    assert u == "https://example.com/fixed", u
    return "固定地址不拼接"


@case("未知平台给出可操作提示")
def _():
    try:
        search_url("不存在的平台", "麦当劳")
    except Exception as e:
        assert "--网址" in str(e), str(e)
        return str(e)
    raise AssertionError("应该抛错")


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            detail = fn()
            print(f"  ✓ {name}")
            if detail:
                print(f"      {detail}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {name}")
            print(f"      {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}（异常）")
            print(f"      {type(e).__name__}: {e}")

    print()
    print(f"  {len(CASES) - failed}/{len(CASES)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
