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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupon_hunter.browser import (  # noqa: E402
    classify,
    looks_like_login_url,
    search_url,
    wait_for_login,
)

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


@case("登录地址识别：美团登录页算登录页")
def _():
    assert looks_like_login_url("https://h5.waimai.meituan.com/login?force=true") is True
    assert looks_like_login_url("https://h5.waimai.meituan.com/waimai/mindex/home") is False
    return "看路径不看参数"


@case("登录地址识别：back_url 里的 /login 不算")
def _():
    # 登录成功后跳回首页，地址尾部带着 back_url=…%2Flogin…，
    # 扫整个 URL 会误判成"还在登录页"，永远发现不了登录成功
    u = (
        "https://h5.waimai.meituan.com/waimai/mindex/home"
        "?back_url=https%3A%2F%2Fh5.waimai.meituan.com%2Flogin%3Fforce%3Dtrue"
    )
    assert looks_like_login_url(u) is False, "参数里的 /login 不该算"
    return "只认路径，参数里的 /login 不算"


@case("登录地址识别：饿了么 /passport 也认")
def _():
    assert looks_like_login_url("https://h5.ele.me/passport/login") is True
    assert looks_like_login_url("https://h5.ele.me/") is False
    return "饿了么的多层路径也认"


@case("登录地址识别：空串和畸形地址不炸")
def _():
    assert looks_like_login_url("") is False
    assert looks_like_login_url("not a url") is False
    return "不抛异常"


class _FakeBody:
    def __init__(self, text):
        self._text = text

    def inner_text(self, timeout=0):
        return self._text


class _FakePage:
    """够 wait_for_login 用的假页面：只要 url / title / body / wait。"""

    def __init__(self, url, title="", text="", closed=False):
        self.url = url
        self._title = title
        self._text = text
        self._closed = closed
        self.waits = 0

    def is_closed(self):
        return self._closed

    def title(self):
        return self._title

    def locator(self, sel):
        return _FakeBody(self._text)

    def wait_for_timeout(self, ms):
        self.waits += 1
        # 真睡一下：wait_for_login 用 time.monotonic() 卡超时，
        # 假页面要是不睡，循环会在几毫秒里空转几十万次
        time.sleep(min(ms, 50) / 1000)


class _FakeCtx:
    def __init__(self, pages):
        self.pages = pages


@case("等到登录成功：页面从登录页变成结果页")
def _():
    page = _FakePage(
        "https://h5.waimai.meituan.com/login?force=true",
        title="登录",
        text="请登录 发送验证码",
    )
    ctx = _FakeCtx([page])

    # 第 2 次轮询时"用户登录完了"，页面变成结果页
    calls = {"n": 0}
    real_wait = page.wait_for_timeout

    def wait_then_switch(ms):
        calls["n"] += 1
        if calls["n"] == 2:
            page.url = "https://h5.waimai.meituan.com/waimai/mindex/search?keyword=x"
            page._title = "美团外卖"
            page._text = "麦当劳（望京店）\n4.5分\n月售999+\n起送 ¥20\n配送 约¥3"
        real_wait(ms)

    page.wait_for_timeout = wait_then_switch

    ok, msg = wait_for_login(ctx, timeout_s=5, poll_ms=1)
    assert ok is True, msg
    assert "登录成功" in msg, msg
    return msg


@case("等到登录成功：一直停在登录页就超时，且说清原因")
def _():
    page = _FakePage(
        "https://h5.waimai.meituan.com/login",
        title="登录",
        text="请登录 发送验证码",
    )
    ok, msg = wait_for_login(_FakeCtx([page]), timeout_s=3, poll_ms=1)
    assert ok is False, "不该判定成功"
    assert "还没登录成功" in msg, msg
    return "超时给出可操作提示"


@case("等到登录成功：中途关掉浏览器要报错，不能装作成功")
def _():
    page = _FakePage("https://h5.waimai.meituan.com/login", closed=True)
    ok, msg = wait_for_login(_FakeCtx([page]), timeout_s=5, poll_ms=1)
    assert ok is False, msg
    assert "关掉" in msg, msg
    return msg


@case("等到登录成功：跳出滑块要停下，不当作登录成功")
def _():
    page = _FakePage(
        "https://h5.waimai.meituan.com/waimai/mindex/home",
        title="安全验证",
        text="为保障账号安全，请拖动滑块完成验证",
    )
    ok, msg = wait_for_login(_FakeCtx([page]), timeout_s=5, poll_ms=1)
    assert ok is False, msg
    assert "验证码" in msg or "滑块" in msg, msg
    return msg


@case("等到登录成功：多标签页时看最后那个")
def _():
    old = _FakePage("https://example.com/", title="别的页", text="x")
    live = _FakePage(
        "https://h5.waimai.meituan.com/waimai/mindex/home",
        title="美团外卖",
        text="麦当劳\n4.5分\n月售999+\n起送 ¥20",
    )
    ok, msg = wait_for_login(_FakeCtx([old, live]), timeout_s=5, poll_ms=1)
    assert ok is True, msg
    return "取 ctx.pages 里最后打开的标签页"


@case("回归：页脚先渲染、滑块 1.5 秒后才弹出，不能判成功")
def _():
    # 这是真事：第一次跑「登录浏览器 麦当劳」时，页面先只有美团页脚
    # （非空、无登录字样），1.5 秒后才弹出「身份核实 / 请按照说明拖动滑块」。
    # 当时只看一眼就断言登录成功，后面读出一堆垃圾。
    page = _FakePage(
        "https://h5.waimai.meituan.com/waimai/mindex/search?keyword=x",
        title="美团外卖",
        text="©美团网 meituan.com 京ICP证070791号 京公网安备 11000002002052号",
    )
    ctx = _FakeCtx([page])
    calls = {"n": 0}
    real_wait = page.wait_for_timeout

    def wait_then_captcha(ms):
        calls["n"] += 1
        if calls["n"] == 2:
            page._title = "身份核实"
            page._text = "身份核实\n请按照说明拖动滑块"
        real_wait(ms)

    page.wait_for_timeout = wait_then_captcha

    ok, msg = wait_for_login(ctx, timeout_s=4, poll_ms=1)
    assert ok is False, f"滑块页被判成登录成功了：{msg}"
    assert "滑块" in msg or "验证码" in msg, msg
    return msg.splitlines()[0]


@case("碰到滑块不是立刻放弃，而是提醒一次后继续等")
def _():
    page = _FakePage(
        "https://h5.waimai.meituan.com/waimai/mindex/home",
        title="身份核实",
        text="请拖动滑块完成验证",
    )
    logs = []
    ok, msg = wait_for_login(
        _FakeCtx([page]), timeout_s=3, poll_ms=1, log=logs.append
    )
    assert ok is False
    assert len(logs) == 1, f"只该提醒一次，实际 {len(logs)} 次：{logs}"
    assert "手动拖" in logs[0], logs[0]
    return logs[0]


@case("要连续 3 次稳定才认成功（不是看一眼就算）")
def _():
    def healthy_page():
        return _FakePage(
            "https://h5.waimai.meituan.com/waimai/mindex/home",
            title="美团外卖",
            text="麦当劳\n4.5分\n月售999+\n起送 ¥20",
        )

    slow = healthy_page()
    ok, msg = wait_for_login(
        _FakeCtx([slow]), timeout_s=5, poll_ms=1, stable_checks=3
    )
    assert ok is True, msg

    fast = healthy_page()
    ok2, _ = wait_for_login(
        _FakeCtx([fast]), timeout_s=5, poll_ms=1, stable_checks=1
    )
    assert ok2 is True
    assert slow.waits > fast.waits, (
        f"stable_checks=3 应该多等几轮，实际 3:{slow.waits} 1:{fast.waits}"
    )
    return f"3 次稳定等了 {slow.waits} 轮，1 次稳定等了 {fast.waits} 轮"


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
