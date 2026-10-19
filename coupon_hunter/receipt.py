"""
截图识别：把外卖/电商结账页的截图，变成可计算的数字。

为什么用截图
────────────────────────────────────────────
外卖和电商平台的页面都是 JS 渲染 + 登录墙，程序抓不到（实测过，见调研结论）。
但**你自己手机上能看到**——截个图，用 OCR 读出来，就是合规且可靠的。

OCR 用 Windows 自带的 Windows.Media.Ocr（`coupon_hunter/ocr.ps1`）：
  · 不用装任何东西
  · 离线运行，图片不外传
  · 支持中文

OCR 会出错，所以解析要容错
────────────────────────────────────────────
实测一张干净的模拟图，OCR 出来的结果是这样的：

    商 品 小 计 45 ． 佣        ← 字符间有空格，全角句号，末尾数字认错
    配 送 3 ． 00
    店 浦 满 减 一 8 ． 00      ← 「铺」认成「浦」
    红 包 巧 ． 00              ← 「5」认成「巧」
    实 扌 36 ． 00              ← 「付」认成「扌」

所以解析思路是：
  1. 先把文本「压紧」：去掉所有空白、全角标点统一成半角
  2. 用**关键词的宽松匹配**认行（允许中间被插空格、个别字认错）
  3. 从行里抽数字，容忍 `．` `。` `,` 等分隔符

核心原则：**宁可认不出，也不瞎猜。** 认不出的项留空，让用户补。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────
# 调用系统 OCR
# ──────────────────────────────────────────────────────────

_OCR_SCRIPT = Path(__file__).with_name("ocr.ps1")


class OcrError(Exception):
    """OCR 失败。message 直接给用户看。"""


def ocr_image(path: str | Path) -> str:
    """对图片做 OCR，返回识别到的文本（每行一条）。

    Windows 上用自带的 Windows.Media.Ocr；其他系统给出明确提示。
    """
    p = Path(path)
    if not p.exists():
        raise OcrError(f"找不到图片：{p}")

    if sys.platform != "win32":
        raise OcrError(
            "截图识别目前只做了 Windows 版本（用系统自带的 OCR）。\n"
            "  其他系统可以先用 `python run.py 外卖比价` 手动粘结账页文本。"
        )

    if not _OCR_SCRIPT.exists():
        raise OcrError(f"缺少 OCR 脚本：{_OCR_SCRIPT}")

    try:
        r = subprocess.run(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(_OCR_SCRIPT), "-Path", str(p.resolve()),
            ],
            capture_output=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired as e:
        raise OcrError("OCR 超时（图片可能太大）") from e
    except Exception as e:
        raise OcrError(f"调用 OCR 失败：{e}") from e

    # Windows 中文控制台的默认输出编码是 GBK（不是 UTF-8）。
    # 早先按 UTF-8 解码，中文全变成乱码，关键词一个都匹配不上。
    # 这里逐个尝试，取第一个能成功解码的。
    def _decode(raw: bytes) -> str:
        for enc in ("utf-8", "gbk", "mbcs"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")

    out = _decode(r.stdout).strip()
    err = _decode(r.stderr).strip()

    if r.returncode != 0:
        # 脚本里 exit 2 表示「系统没有 OCR 引擎」
        if r.returncode == 2 or "OCR 引擎" in err:
            raise OcrError(
                "系统没有可用的中文 OCR 引擎。\n"
                "  去「设置 → 时间和语言 → 语言」里安装中文语言包（含手写/OCR 组件）后重试。"
            )
        raise OcrError(f"OCR 失败：{err[:300] or '未知错误'}")

    if not out:
        raise OcrError("OCR 没识别出任何文字。图片可能太模糊，或者不是文字截图。")

    return out


# ──────────────────────────────────────────────────────────
# 文本归一化
# ──────────────────────────────────────────────────────────

# 全角 → 半角（数字、标点、字母）
_FULLWIDTH = {
    ord("０"): "0", ord("１"): "1", ord("２"): "2", ord("３"): "3", ord("４"): "4",
    ord("５"): "5", ord("６"): "6", ord("７"): "7", ord("８"): "8", ord("９"): "9",
    ord("．"): ".", ord("。"): ".", ord("，"): ",", ord("："): ":",
    ord("￥"): "¥", ord("－"): "-", ord("—"): "-", ord("–"): "-",
    ord("　"): " ",
}


def normalize(text: str) -> str:
    """把 OCR 文本压紧：全角转半角、去掉所有空白。

    为什么要去空白：OCR 常在汉字之间插空格（「商 品 小 计」），
    不压紧的话关键词匹配全都会失败。
    """
    s = str(text).translate(_FULLWIDTH)
    s = re.sub(r"\s+", "", s)
    return s


# ──────────────────────────────────────────────────────────
# 字段识别
# ──────────────────────────────────────────────────────────

# 每个逻辑字段配多个关键词。匹配时用「压紧后」的文本，
# 并且允许关键词中间被 OCR 插字符（用正则的 .{0,2} 放宽）。
_FIELDS: list[tuple[str, tuple[str, ...]]] = [
    ("items",         ("商品小计", "菜品小计", "商品合计", "菜品合计", "餐品小计",
                       "商品金额", "菜品金额", "商品总额", "小计")),
    # 「包装费」的「费」常被 OCR 丢掉，所以单独加一个「包装」
    ("packing",       ("包装费", "打包费", "餐盒费", "包装袋", "餐盒", "包装", "打包")),
    ("delivery",      ("配送费", "跑腿费", "配送", "运费")),
    ("shop_discount", ("店铺满减", "店铺优惠", "商家优惠", "满减", "商品优惠")),
    ("coupon",        ("优惠券", "平台券", "代金券", "红包券", "券")),
    ("red_packet",    ("红包", "立减", "抵扣")),
    # 「实付」的「付」常被认成「扌」「什」之类，所以单独放一个「实」
    # （「实」本身在结账页里基本只出现在「实付」这个词里）
    ("final",         ("实付", "合计", "总计", "应付", "需支付", "支付", "实")),
]


def _fuzzy(keyword: str) -> re.Pattern:
    """把关键词变成「允许中间夹 0-2 个字符」的正则。

    这样「商 品 小 计」压紧成「商品小计」能匹配，
    个别字认错（「店铺」→「店浦」）也能靠部分匹配兜住。
    """
    parts = list(keyword)
    return re.compile(".{0,2}".join(re.escape(c) for c in parts))


# 预先编译，避免每行都重编
_FIELD_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    (name, [_fuzzy(k) for k in keys]) for name, keys in _FIELDS
]

# 数字：允许 ¥ 前缀、负号、千分位逗号、小数点
_NUM = re.compile(r"[-−]?¥?(\d{1,6}(?:[.,]\d{1,2})?)")


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def parse_receipt(text: str) -> dict:
    """从 OCR 文本（或手工粘贴的结账页文本）里抽金额。

    返回 dict，只含认出来的字段：
        items, delivery, packing, shop_discount, coupon, red_packet,
        final（平台显示的实付，用来核对）, member（是否提到会员）

    认不出的字段**不会出现在结果里**——宁可缺，也不要瞎填。
    """
    result: dict = {}
    if not text:
        return result

    for raw_line in str(text).splitlines():
        line = normalize(raw_line)
        if not line:
            continue

        # 找这一行属于哪个字段。按 _FIELDS 的顺序试，第一个命中算。
        # 「商品小计」在「小计」前面，所以不会被后者抢走。
        field = None
        for name, patterns in _FIELD_PATTERNS:
            if any(p.search(line) for p in patterns):
                field = name
                break
        if field is None:
            continue

        # 抽这一行里的第一个数字
        # 先去掉关键词部分，避免把「满99减10」里的 99 当金额
        m = _NUM.search(line)
        if not m:
            continue
        value = _to_float(m.group(1))
        if value is None:
            continue
        # 抽到 0 大概率是 OCR 认错了（比如「5」被认成「巧」，行里只剩「00」）。
        # 这种情况宁可留空让用户补，也不要填个 0 进去——
        # 0 会让「红包」这一项看起来像真的没有，比缺了更误导。
        if value == 0 and field in ("shop_discount", "coupon", "red_packet", "final"):
            continue

        if field in ("shop_discount", "coupon", "red_packet"):
            # 折扣类一律取正数（「-8」和「8」都是减 8 的意思）
            value = abs(value)
            # 同类出现多次就累加（比如两行红包）
            result[field] = round(result.get(field, 0.0) + value, 2)
        else:
            # 其余字段保留第一次出现的值
            result.setdefault(field, value)

    if "会员" in str(text):
        result["member"] = True
    return result


def describe(result: dict) -> str:
    """把解析结果排成一行给人看。"""
    if not result:
        return "什么都没认出来"
    labels = [
        ("items", "菜品"), ("delivery", "配送"), ("packing", "打包"),
        ("shop_discount", "店铺满减"), ("coupon", "平台券"),
        ("red_packet", "红包"), ("final", "实付"),
    ]
    bits = [f"{name} {result[k]:g}" for k, name in labels if k in result]
    if result.get("member"):
        bits.append("会员")
    return " | ".join(bits) if bits else "什么都没认出来"
