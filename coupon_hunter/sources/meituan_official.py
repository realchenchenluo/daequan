"""
数据源二：美团官方「AI 发券」接口（券直接发进你的美团账号，力度最大）

⚠️ 读之前先知道这是什么
────────────────────────────────────────────
这是美团自己做给 AI 助手 / 分销媒体用的官方接口，全程走 meituan.com 自己的域名：
    登录：peppermall.meituan.com/eds/claw/login/...
    发券：media.meituan.com/fulishemini/couponActivity/aiSendCouponDistribution

它跟你在美团 App 里领券是同一件事，只是换成了程序来点。
券是真的、官方发的、直接进你账号，所以力度通常比通用口令券大。

需要你提供：美团绑定手机号 + 收到的短信验证码（只用一次，之后靠 token）。

「aiScene」是什么？
────────────────────────────────────────────
它是一个推广渠道编号。你通过哪个渠道领券，推广方就从美团拿佣金。
换句话说：这条链路上的所有人（包括我给你的默认值）都是靠你领券赚钱的。
这不影响你省钱——券是美团出的，你该省多少省多少。
但你有权知道这件事，所以写在这里。

安全边界：
  - 手机号和 token 只写进本地 data/auth.json，代码里没有任何一处往外发。
  - 登录走的是美团官方域名，不是第三方服务器。
  - 本工具不会、也无法读取你的账号密码（美团登录只用短信验证码）。
"""

from __future__ import annotations

import hashlib
import random
import time

from ..http import HttpError, post_json
from ..models import Coupon, FetchResult
from ..store import is_claimed_today, load_auth, mask_phone, save_auth

BASE_URL = "https://peppermall.meituan.com"
SMS_GET_PATH = "/eds/claw/login/sms/code/get"
SMS_VERIFY_PATH = "/eds/claw/login/sms/code/verify"
TOKEN_VERIFY_PATH = "/eds/claw/login/token/verify"

ISSUE_URL = "https://media.meituan.com/fulishemini/couponActivity/aiSendCouponDistribution"

# 「aiScene」是推广渠道编号，接口必填。这里刻意**不内置任何人的编号**：
#   · 内置别人的编号 = 你领券产生的佣金归那个人。自己用无所谓，
#     但如果这个项目被公开或分享，就等于拿别人的推广位给别人导流，会惹麻烦。
#   · 想要自己的编号：去 https://union.meituan.com 免费注册，填到 config.json。
AI_SCENE_HINT = (
    "还没配置美团推广渠道号。\n"
    "  去 https://union.meituan.com 免费注册，拿到你的推广位编号，\n"
    '  填进 config.json 里 meituan_official 那条的 "ai_scene" 字段。'
)

# 登录接口的业务错误码 -> 人话
_LOGIN_CODE_MSG = {
    20002: "验证码刚发过，请 1 分钟后再试",
    20003: "验证码错误或已过期，请重新获取",
    20004: "该手机号没有注册过美团，请先用美团 App 注册",
    20006: "今天发验证码的次数已用完（上限 5 次），请明天再试",
    20007: "该手机号今日短信总量已达上限，请明天再试",
    20010: "需要先完成一次安全验证，请到美团 App 里验证后再试",
}


def generate_device_token(seed: str) -> str:
    """生成一个假的「设备指纹」。

    接口要求传 uuid 来标识设备。官方实现是 MD5(seed + 毫秒时间戳 + 随机数)，
    这里保持一致。生成后固定不变，否则每次请求都会被当成新设备。
    """
    raw = f"{seed}{int(time.time() * 1000)}{random.randint(0, 1000)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────
# 登录三步曲
# ──────────────────────────────────────────────────────────

def send_sms(phone: str) -> str:
    """第一步：发验证码。返回本次使用的 device_token。"""
    auth = load_auth()
    device = auth.get("device_token") or generate_device_token(phone)
    auth["device_token"] = device
    auth["phone_masked"] = mask_phone(phone)
    save_auth(auth)

    resp = post_json(
        BASE_URL + SMS_GET_PATH,
        {"mobile": phone, "uuid": device},
        timeout=15,
    )
    code = resp.get("code")
    if code == 200:
        return device
    msg = _LOGIN_CODE_MSG.get(code)
    if code == 20010 and resp.get("data", {}).get("redirectUrl"):
        msg += f"\n验证链接：{resp['data']['redirectUrl']}"
    raise HttpError(msg or f"发送验证码失败：{resp.get('msg') or resp}")


def verify_sms(phone: str, sms_code: str) -> str:
    """第二步：校验验证码，成功后把 user_token 存到本地。返回 token。"""
    auth = load_auth()
    device = auth.get("device_token") or generate_device_token(phone)

    resp = post_json(
        BASE_URL + SMS_VERIFY_PATH,
        {"mobile": phone, "smsVerifyCode": sms_code, "uuid": device},
        timeout=15,
    )
    code = resp.get("code")
    if code != 200:
        raise HttpError(_LOGIN_CODE_MSG.get(code) or f"登录失败：{resp.get('msg') or resp}")

    data = resp.get("data") or {}
    token = data.get("token") or data.get("userToken") or data.get("user_token")
    if not token:
        raise HttpError(f"登录成功但没拿到 token，返回内容是：{data}")

    auth.update(
        {
            "user_token": token,
            "phone_masked": mask_phone(phone),
            "device_token": device,
            "login_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    save_auth(auth)
    return token


def verify_token(token: str) -> bool:
    """第三步：检查 token 还有效吗。"""
    try:
        resp = post_json(
            BASE_URL + TOKEN_VERIFY_PATH,
            {},
            params={"token": token},
            timeout=15,
        )
    except HttpError:
        return False

    if resp.get("code") == 200:
        data = resp.get("data") or {}
        # 有些实现会在 data.valid 里给布尔值，没给就认为 200 即有效
        return bool(data.get("valid", True))
    return False


def logout() -> None:
    from ..store import clear_auth

    clear_auth()


# ──────────────────────────────────────────────────────────
# 领券
# ──────────────────────────────────────────────────────────

def _fen_to_yuan(fen) -> float | None:
    try:
        return round(int(fen) / 100, 2)
    except (TypeError, ValueError):
        return None


def issue_coupons(token: str, ai_scene: str) -> tuple[list[Coupon], str, str]:
    """调用发券接口。返回 (券列表, 活动名, 活动链接)。"""
    if not ai_scene:
        raise HttpError(AI_SCENE_HINT)

    resp = post_json(
        ISSUE_URL,
        {"token": token, "aiScene": ai_scene},
        timeout=20,
        # 必须保持证书校验开启：请求体里带着你的 user_token，
        # 关掉校验等于把登录凭证裸奔在网络上。已实测该域名证书链正常。
        verify=True,
    )
    code = resp.get("code")
    data = resp.get("data") or {}

    if code == 200:
        coupons: list[Coupon] = []
        for item in data.get("couponList", []) or []:
            value = _fen_to_yuan(item.get("couponValue"))
            threshold = _fen_to_yuan(item.get("priceLimit"))
            coupons.append(
                Coupon(
                    platform="美团",
                    title=item.get("couponName") or "美团券",
                    code="",
                    guideline="已直接发放到你的美团账号，打开 App 即可使用",
                    source="美团官方直发",
                    tag="官方直发",
                    threshold=threshold,
                    value=value,
                    valid_from=_ts(item.get("couponStartTime")),
                    valid_to=_ts(item.get("couponEndTime")),
                )
            )
        return coupons, data.get("activityName", ""), data.get("activityLink", "")

    if code == 1014:
        return [], data.get("activityName", ""), data.get("activityLink", "")

    if code == 401:
        raise HttpError("登录已过期，请重新执行「美团登录」")

    if code in (509, 50200):
        raise HttpError("请求太频繁了，等一会儿再试")

    raise HttpError(f"领券失败（code={code}, msg={resp.get('msg')}）")


def _ts(ms) -> str:
    if not ms:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(int(ms) / 1000))
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────
# 给数据源注册表调用的入口
# ──────────────────────────────────────────────────────────

def fetch_meituan_official(cfg: dict) -> FetchResult:
    """在「搜券」流程里被调用。

    ⚠️ 重要设计约束：默认只做「查状态」，绝不顺手领券。
    美团这个接口只有「发券」没有「查券」，也就是说调一次就会真的把券领掉。
    如果搜券时自动调用它，用户只是想看看有什么券，结果当天唯一一次的领取机会
    就被悄悄用掉了——这是不可接受的副作用。所以默认 auto_claim=false，
    想自动领就必须在 config.json 里显式打开。
    """
    result = FetchResult()
    ai_scene = (cfg.get("ai_scene") or "").strip()
    label = cfg.get("label", "美团官方直发券")
    auto_claim = bool(cfg.get("auto_claim", False))

    if not ai_scene:
        result.notes.append(
            f"[{label}] 未配置推广渠道号（ai_scene），已跳过。"
            "去 https://union.meituan.com 免费注册后可填进 config.json。"
        )
        return result

    auth = load_auth()
    token = auth.get("user_token")

    if not token:
        result.notes.append(
            f"[{label}] 还没登录美团，已跳过。想用这个源请先运行：python run.py 登录"
        )
        return result

    if not verify_token(token):
        result.notes.append(f"[{label}] 登录已过期，请重新运行：python run.py 登录")
        return result

    # 默认路径：只报告状态，不动用户的领取机会
    if not auto_claim:
        if is_claimed_today("美团"):
            result.notes.append(f"[{label}] 已登录，今天已经领过了。")
        else:
            result.notes.append(
                f"[{label}] 已登录，今天还没领。运行「python run.py 领券」把专属券领进账号。"
            )
        return result

    try:
        coupons, activity_name, activity_link = issue_coupons(token, ai_scene)
    except HttpError as e:
        result.errors.append(f"[{label}] {e.message}")
        return result

    if not coupons:
        if is_claimed_today("美团"):
            result.notes.append(f"[{label}] 今天已经领过了，明天再来")
        else:
            result.notes.append(f"[{label}] 美团今天暂时没有新券可领")
    else:
        result.coupons.extend(coupons)
        result.notes.append(f"[{label}] 本次领到 {len(coupons)} 张券，已进你的美团账号")

    if activity_name:
        result.coupons.append(
            Coupon(
                platform="美团",
                title=f"今日活动：{activity_name}",
                url=activity_link,
                guideline="点链接直达活动会场",
                source=label,
                tag="会场",
            )
        )

    return result
