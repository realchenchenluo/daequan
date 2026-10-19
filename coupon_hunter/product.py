"""
商品页截图解析 —— 从「商品详情页」而不是「结账页」里读信息。

为什么单独做
────────────────────────────────────────────
用户实际会截的是商品页（比如美团外卖的某个蛋糕），上面有：
    商家名、商品名、一口价、原价、立省
这些够算出「这单多少钱」，不需要结账页。

真实截图的 OCR 有多烂
────────────────────────────────────────────
用一张真实的美团商品页截图实测，两种引擎读出来分别是：

    Windows OCR:                  tesseract.js:
    糕 研 社                      一 0 价 y19.5 有 ETE 神 抢 手
    一 囗 价 ￥ 19 · 5            海盐 艺 士 蛋 炉 ( 超 请 更 )
    立 省 ￥ 1a3
    ￥ 29g 月 售 30 囗 +

于是策略是：
  · **能救的救**：囗→口、·→.、一0价→一口价、y19.5→¥19.5
  · **救不了的承认**：¥1a3 这种数字混字母的，整段作废，不截取其中一部分
    （截成 1 或 3 都会得到完全错的金额，比读不出来更糟）
  · 价格读不出来就明确说，不猜

不硬猜商家名和商品名
────────────────────────────────────────────
真实截图版式千差万别，硬猜一个错名字比空着更糟——用户会以为认对了。
所以提取不到就留空。
"""

from __future__ import annotations

import re

from .receipt import normalize

# 形近字纠正。都是从真实截图里踩出来的。
_LOOKALIKE = {
    "囗": "口",
    "·": ".",
    "・": ".",
    "—": "-",
    "–": "-",
    "＜": " ",
}

# 价格类关键词
_PRICE_KEYS = ("一口价", "到手价", "现价", "秒杀价", "团购价", "活动价", "折后价", "特价", "售价")
_ORIGINAL_KEYS = ("原价", "划线价", "门市价", "市场价")
_SAVE_KEYS = ("立省", "已省")

# 明显不是价格的数字行（销量、评分、日期、时钟、网速）
_NOISE = re.compile(r"月售|已售|评分|人觉得|推荐|回头客|评价|年|月|日|\d{1,2}:\d{2}|MB/")

# ¥ 后面必须是纯数字，且数字后不能紧跟字母/数字。
# 「¥1a3」= OCR 把 10.3 认成 1a3，必须整段作废。
_YEN_AMOUNT = re.compile(r"¥\s*(\d{1,6}(?:[.·]\d{1,2})?)(?![\dA-Za-z])")
_FALLBACK_NUM = re.compile(r"(\d{1,6}(?:[.·]\d{1,2})?)(?![\dA-Za-z])")


def _norm(text: str) -> str:
    """归一化：全角转半角、去掉空白、修形近字。

    实测两个高频误识（两种 OCR 引擎都会犯）：
      · 「一口价」的「口」被认成 0
      · 「¥」被认成 y
    """
    s = normalize(text)
    for a, b in _LOOKALIKE.items():
        s = s.replace(a, b)
    s = re.sub(r"一[0Oo口]价", "一口价", s)
    s = re.sub(r"(?<![A-Za-z])y(?=\d)", "¥", s)
    return s


def _clean_amount(raw: str) -> float | None:
    try:
        return float(raw.replace("·", ".").replace(",", ""))
    except ValueError:
        return None


def _amount_from_line(line: str) -> tuple[float | None, str]:
    """从一行里取金额，返回 (值, 说明)。读不出来就说原因。

    规则：
      · 有 ¥：只认紧跟在 ¥ 后面的纯数字，数字后不能紧跟字母。
      · 没有 ¥：退回找一串数字（用于「满30减15」这类文本）。
    """
    m = _YEN_AMOUNT.search(line)
    if m:
        v = _clean_amount(m.group(1))
        if v is not None:
            return v, ""
        return None, "不是有效数字"

    if "¥" in line:
        tail = line.split("¥", 1)[1][:10]
        return None, f"「{tail}」里数字混了字母，OCR 认错了"

    m2 = _FALLBACK_NUM.search(line)
    if m2:
        v = _clean_amount(m2.group(1))
        if v is not None:
            return v, ""
    return None, "没找到数字"


def parse_product_page(text: str) -> dict:
    """从商品页 OCR 文本里抽信息。

    返回的键（只含认出来的）：
        merchant / product / price / original / saved
    另有：
        suspicious  列表，说明哪些字段可能读错了
        raw_lines   归一化后的行，方便排查
    """
    result: dict = {"suspicious": [], "raw_lines": []}
    if not text:
        return result

    lines = [_norm(l) for l in str(text).splitlines() if l.strip()]
    result["raw_lines"] = lines

    price = original = saved = None
    price_line = ""

    for line in lines:
        # ── 现价 ──
        if price is None and (any(k in line for k in _PRICE_KEYS)
                              or ("价" in line and re.search(r"\d", line))):
            price_line = line
            v, why = _amount_from_line(line)
            if v is not None and 0 < v < 100000:
                price = v
            else:
                result["suspicious"].append(f"现价读不出来（{why}）：「{line}」")
            continue

        # ── 原价 ──
        if original is None and any(k in line for k in _ORIGINAL_KEYS):
            v, why = _amount_from_line(line)
            if v is not None and 0 < v < 100000:
                original = v
            else:
                result["suspicious"].append(f"原价读不出来（{why}）：「{line}」")
            continue

        # ── 立省 ──
        if saved is None and any(k in line for k in _SAVE_KEYS):
            v, why = _amount_from_line(line)
            if v is not None and 0 < v < 100000:
                saved = v
            else:
                result["suspicious"].append(f"立省读不出来（{why}）：「{line}」")
            continue

    # 有些页面把原价和销量写一行（「¥29.8 月售300+」），上面按关键词匹配不到。
    # 这里补一刀：找带 ¥、不含销量/时间、且比现价大的行。
    if original is None and price is not None:
        for line in lines:
            if line == price_line or _NOISE.search(line) or "¥" not in line:
                continue
            v, _why = _amount_from_line(line)
            if v is not None and price < v < 100000:
                original = v
                break

    # 商家名：价格行之前的短中文行。启发式，认不出就留空。
    if price_line:
        idx = lines.index(price_line)
        for line in reversed(lines[:idx]):
            plain = re.sub(r"[^\u4e00-\u9fa5A-Za-z]", "", line)
            han = len(re.findall(r"[\u4e00-\u9fa5]", plain))
            latin = len(re.findall(r"[A-Za-z]", plain))
            # 至少 3 个汉字，或 2 个汉字且不含拉丁字母。
            # 目的：挡住 OCR 头部噪声（实测把「和S于」这种乱码当成商家名）。
            if not (han >= 3 or (han == 2 and latin == 0)):
                continue
            if 2 <= len(plain) <= 12:
                if any(k in plain for k in ("推荐", "评价", "商品", "描述",
                                            "购物车", "外卖", "查看", "首页")):
                    continue
                result["merchant"] = plain
                break

    # 商品名：含常见食品/商品后缀的行
    for line in lines:
        if _NOISE.search(line):
            continue
        plain = re.sub(r"\s+", "", line)
        if 3 <= len(plain) <= 30 and any(
            k in plain for k in ("蛋糕", "奶茶", "咖啡", "拿铁", "汉堡", "披萨",
                                 "套餐", "炸鸡", "寿司", "果汁", "饭", "面",
                                 "粥", "汤", "串")
        ):
            result["product"] = plain
            break

    if price is not None:
        result["price"] = price
    if original is not None:
        result["original"] = original
    if saved is not None:
        result["saved"] = saved

    # 一致性检查：原价 − 立省 应该 ≈ 现价。对不上说明有数字读错了。
    if price is not None and original is not None and saved is not None:
        if abs((original - saved) - price) > 0.5:
            result["suspicious"].append(
                f"原价 {original:g} − 立省 {saved:g} = {original - saved:g}，"
                f"和现价 {price:g} 对不上，可能有数字认错了"
            )
    elif price is not None and original is not None and original <= price:
        result["suspicious"].append(f"原价 {original:g} 不比现价 {price:g} 高，可能读错了")

    return result


def describe_product(info: dict) -> str:
    """人话描述解析结果。"""
    bits = []
    if info.get("merchant"):
        bits.append(f"商家 {info['merchant']}")
    if info.get("product"):
        bits.append(f"商品 {info['product']}")
    if info.get("price") is not None:
        bits.append(f"现价 {info['price']:g}")
    if info.get("original") is not None:
        bits.append(f"原价 {info['original']:g}")
    if info.get("saved") is not None:
        bits.append(f"立省 {info['saved']:g}")

    s = " | ".join(bits) if bits else "没认出有效信息"
    if info.get("suspicious"):
        s += "\n可能有问题：" + "；".join(info["suspicious"])
    return s
