"""
商品页截图解析 —— 从「商品详情页」而不是「结账页」里读信息。

为什么需要两种解析
────────────────────────────────────────────
1. **坐标解析**（parse_product_blocks）—— 推荐。用 OCR 返回的文本框位置，
   把「价格标签」和它对应的「金额」按距离配对。真实截图里标签和数字
   经常被拆成两个块，光看文本顺序会配错。
2. **按行解析**（parse_product_page）—— 退路。只有纯文本时用
   （比如用户手工粘贴、或者跑单元测试）。

真实截图踩过的坑（都是实测，不是猜）
────────────────────────────────────────────
· 京东的版式：`¥10.9起` 是现价，`已补¥7.1` 是优惠额，`¥18` 是原价。
  纯按文本顺序会把 7.1 当成现价。
· 页面上的「1.11低价热卖」「2026.10.04」这类横幅/日期，也很像金额，
  必须排除：只认「整块就是一个金额」的文本块。
· 「折后价」的数字可能在标签**上方**（香辣鸡架那张）。
· 同一个人可能既有「折后价28.47」又有「券后约24.8」，后者才是实付。
· 「￥29.8 1月售300+」去空格后粘成「29.81」，OCR 会读错。
  → 用算术关系纠正：原价 = 现价 + 优惠。
"""

from __future__ import annotations

import re

from .receipt import normalize, ocr_blocks

# ──────────────────────────────────────────────────────────
# 归一化
# ──────────────────────────────────────────────────────────

# 形近字纠正。都是从真实截图里踩出来的。
_LOOKALIKE = {
    "囗": "口",
    "·": ".",
    "・": ".",
    "—": "-",
    "–": "-",
    "＜": " ",
}


def _norm(text: str) -> str:
    """全角转半角、去空白、修形近字。

    两个高频误识（Windows OCR 和 tesseract.js 都会犯）：
      · 「一口价」的「口」被认成 0
      · 「¥」被认成 y
    """
    s = normalize(text)
    for a, b in _LOOKALIKE.items():
        s = s.replace(a, b)
    s = re.sub(r"一[0Oo口]价", "一口价", s)
    s = re.sub(r"(?<![A-Za-z])y(?=\d)", "¥", s)
    return s


# ──────────────────────────────────────────────────────────
# 关键词
# ──────────────────────────────────────────────────────────

# 价格标签，带优先级：数字越大越优先采用。
# 「券后/到手」才是实际付的钱，比「一口价/折后价」更该信。
_PRICE_LABELS = [
    (10, ("券后", "到手价", "实付")),
    (8, ("一口价", "折后价", "神券价", "现价", "秒杀价", "团购价",
         "活动价", "特价", "售价", "会员价", "折后")),
]
_PRICE_KEYS = tuple(k for _, ks in _PRICE_LABELS for k in ks)

_ORIGINAL_KEYS = ("原价", "划线价", "门市价", "市场价")
# 「已补」「补贴」是京东的写法，等价于优惠额
_SAVE_KEYS = ("立省", "已省", "已补", "补贴")

# 明显不是价格的文本
_NOISE = re.compile(
    r"月售|已售|评分|人觉得|推荐|回头客|评价|浏览|好评|折扣$|"
    r"\d{1,2}:\d{2}|MB/|低价热卖|超级补贴|限购|先享后付|凑单|配送费"
)

# 整块就是一个金额（可带 ¥、起、元后缀）。用来判断「这个文本块是不是纯数字」。
_AMOUNT_BLOCK = re.compile(r"^[¥￥]?\s*(\d{1,6}(?:[.·]\d{1,2})?)\s*[起元^！!]*$")

# 行内金额：¥ 后面必须是纯数字，且数字后不能紧跟字母/数字。
_YEN_AMOUNT = re.compile(r"¥\s*(\d{1,6}(?:[.·]\d{1,2})?)(?![\dA-Za-z])")
_FALLBACK_NUM = re.compile(r"(\d{1,6}(?:[.·]\d{1,2})?)(?![\dA-Za-z])")


def _clean_amount(raw: str) -> float | None:
    try:
        return float(raw.replace("·", ".").replace(",", ""))
    except ValueError:
        return None


def _amount_from_line(line: str) -> tuple[float | None, str]:
    """从一行文本里取金额，返回 (值, 说明)。读不出来就说原因。

    「¥1a3」这类数字混字母的整段作废——截取其中一部分（只剩 1 或 3）
    会得到完全错的金额，比读不出来更糟。
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


# ──────────────────────────────────────────────────────────
# 坐标解析（推荐）
# ──────────────────────────────────────────────────────────

def _blocks_to_lines(blocks) -> list[str]:
    """把坐标块按行合并成文本行，方便排查和走按行解析。"""
    rows: list[list[tuple[float, str]]] = []
    for text, x, y, w, h in sorted(blocks, key=lambda b: b[2]):
        placed = False
        for row in rows:
            if abs(row[0][0] - y) <= max(8.0, h * 0.6):
                row.append((x, text))
                placed = True
                break
        if not placed:
            rows.append([(x, text)])
    return [" ".join(t for _x, t in sorted(row)) for row in rows]


def _amount_inline(text: str) -> float | None:
    """标签块自己带金额时直接取（「一口价￥15.9」）。"""
    v, _why = _amount_from_line(text)
    return v


def _split_block(text: str):
    """把一个文本块里的「标签」和「金额」按先后顺序配对。

    动机：真实截图常把多个标签塞进同一块，例如京东的
        「一口价 | 已补￥7.1」
    如果只判断「这块含价格标签且含金额」，就会把 7.1 当成现价（实测错）。

    规则：每个金额归属于**它前面最近的那个标签**；
    如果金额在最前面（标签在后面），说明它属于上一段内容，本块不认它，
    交给邻近的纯金额块去配（实测「￥44.8券后约」这种情况）。

    返回 [(kind, value)]，kind 是 "price" / "save" / "original"。
    """
    t = _norm(text)
    if not t:
        return []

    labels = []          # (pos, kind, priority)
    for level, keys in _PRICE_LABELS:
        for k in keys:
            start = 0
            while True:
                i = t.find(k, start)
                if i < 0:
                    break
                labels.append((i, "price", level))
                start = i + len(k)
    for k in _SAVE_KEYS:
        start = 0
        while True:
            i = t.find(k, start)
            if i < 0:
                break
            labels.append((i, "save", 5))
            start = i + len(k)
    for k in _ORIGINAL_KEYS:
        start = 0
        while True:
            i = t.find(k, start)
            if i < 0:
                break
            labels.append((i, "original", 5))
            start = i + len(k)

    if not labels:
        return []

    labels.sort()

    out = []
    amount_re = re.compile(r"¥?\s*(\d{1,6}(?:[.·]\d{1,2})?)(?![\dA-Za-z])")
    amount_count = len(list(amount_re.finditer(t)))
    # 逐个金额，找它前面最近的标签
    for m in amount_re.finditer(t):
        v = _clean_amount(m.group(1))
        if v is None or not (0 < v < 100000):
            continue
        pos = m.start()
        owner = None
        for lp, kind, prio in labels:
            if lp <= pos:
                owner = (lp, kind, prio)
            else:
                break
        if owner is None:
            # 金额在标签前面：不认（可能是上一段的数）
            continue
        # 价格要求更严：必须有 ¥ 前缀，或者整块只有这一个金额。
        # 实测「一口价1已补￥25.3」里的「1」是 OCR 把竖线认成了 1，
        # 不设这个限制会把它当成现价 1 元。
        if owner[1] == "price":
            has_yen = pos > 0 and t[max(0, pos - 2):pos].strip().endswith("¥")
            if not has_yen and amount_count > 1:
                continue
        out.append((owner[1], v, owner[2]))
    return out


def _near_amount(blocks, idx: int, used: set[int],
                 allow_inline: bool = True) -> tuple[float, int] | None:
    """给第 idx 个标签块找对应金额。

    严格规则（松了就会把横幅、日期当成价格，实测踩过）：
      1. 标签块自己带金额 → 直接用
      2. 只认「整块就是一个金额」的块（_AMOUNT_BLOCK），
         这样「1.11低价热卖」「2026.10.04」会被自动排除
      3. 距离要求：同一行（纵向偏差 < 0.8 倍行高），或者紧邻上一行/下一行
         （纵向偏差 < 1.6 倍行高）且水平有重叠
    """
    text, x, y, w, h = blocks[idx]

    # allow_inline=False 的场景：这个块里虽然有钱，但它归属于块内的另一个标签
    # （比如「一口价|已补￥7.1」里的 7.1 是已补），不能再拿它当这个标签的值。
    if allow_inline:
        inline = _amount_inline(text)
        if inline is not None and 0 < inline < 100000:
            return inline, idx

    best: tuple[float, int] | None = None
    best_score = 1e18

    for j, (t2, x2, y2, w2, h2) in enumerate(blocks):
        if j == idx or j in used:
            continue
        m = _AMOUNT_BLOCK.fullmatch(t2.strip())
        if not m:
            continue
        v = _clean_amount(m.group(1))
        if v is None or not (0 < v < 100000):
            continue

        dy = y2 - y
        ady = abs(dy)
        row_h = max(h, h2)

        same_row = ady <= max(10.0, row_h * 0.8)
        if same_row:
            dx = x2 - x
            # 左右都允许：实测京东的版式是「￥10.9起  一口价|已补￥7.1」，
            # 金额在主标签左边。但左边远一点要轻微扣分，避免抢到别的数。
            if abs(dx) > 520:
                continue
            score = ady * 4 + abs(dx) * 0.25 + (0.0 if dx >= 0 else 12.0)
        elif ady <= row_h * 1.6:
            # 紧邻的上一行/下一行，要求水平有重叠
            overlap = min(x + w, x2 + w2) - max(x, x2)
            if overlap <= 0:
                continue
            score = ady * 1.5 + 40
        else:
            continue

        if score < best_score:
            best_score = score
            best = (v, j)

    return best


def _merchant_from_blocks(blocks, price_y: float | None) -> str:
    """猜商家名。优先【】里的品牌，其次价格上方最近的短中文块。

    认不出就返回空——真实截图的横幅文字会被误认（实测把「浓郁香草」
    「百事可乐」「放肆撸串」当成过商家名），空着比认错好。
    """
    # 1) 【品牌】形式（京东商品名常见）
    for text, *_rest in blocks:
        m = re.search(r"[【\[]([^】\]]{2,20})[】\]]", text)
        if m:
            name = m.group(1).strip()
            if name and not re.search(r"[0-9]", name):
                return name

    # 2) 价格上方最近的短中文块
    if price_y is None:
        return ""
    best = ""
    best_y = -1.0
    for text, x, y, w, h in blocks:
        if y >= price_y:
            continue
        plain = re.sub(r"[^\u4e00-\u9fa5A-Za-z]", "", text)
        han = len(re.findall(r"[\u4e00-\u9fa5]", plain))
        latin = len(re.findall(r"[A-Za-z]", plain))
        if not (han >= 3 or (han == 2 and latin == 0)):
            continue
        if not (2 <= len(plain) <= 12):
            continue
        if any(k in plain for k in ("推荐", "评价", "商品", "描述", "购物车",
                                    "外卖", "查看", "首页", "配送", "自提",
                                    "预订", "拼单", "更省", "好吃", "美味")):
            continue
        if y > best_y:          # 越靠近价格越可信
            best, best_y = plain, y
    return best


def _product_from_blocks(blocks, price_y: float | None = None) -> str:
    """猜商品名。认不出返回空。

    只在**价格下方**找——真实页面的商品标题都在价格栏下面。
    实测踩过：不限位置时会把图片里的「百事可乐」logo 当成商品名。
    """
    cands = []
    for text, x, y, w, h in blocks:
        if price_y is not None and y < price_y:
            continue
        plain = re.sub(r"\s+", "", text)
        if _NOISE.search(plain):
            continue
        if not (3 <= len(plain) <= 40):
            continue
        if not any(k in plain for k in ("蛋糕", "奶茶", "咖啡", "拿铁", "汉堡", "披萨",
                                        "套餐", "炸鸡", "寿司", "果汁", "鸡架", "小食",
                                        "桶", "青提", "玫瑰", "可乐", "饭", "面")):
            continue
        cands.append((y, plain))
    if not cands:
        return ""
    cands.sort(key=lambda c: c[0])
    return cands[0][1]


def parse_product_blocks(blocks) -> dict:
    """按坐标解析商品页。blocks 来自 receipt.ocr_blocks()。

    两步：
      1. 每块先做「块内配对」（_split_block），把 一口价/已补/原价 各自的钱分清楚
      2. 有价格标签但块内没金额的，找邻近的纯金额块补上
         （实测「折后价」的 28.47 在它上方、「券后约」的 24.8 在它右边）
    """
    result: dict = {"suspicious": [], "raw_lines": _blocks_to_lines(blocks)}
    if not blocks:
        return result

    used: set[int] = set()
    price = None
    price_prio = -1
    price_y = None
    # 商品名要从「价格区」往下找。用**第一个**价格标签的 y 作为参照，
    # 因为最终选中的可能是页面底部更靠下的「券后价」，那时标题反而在它上面。
    anchor_y = None
    for _t, _x, _y, _w, _h in blocks:
        _n = _norm(_t)
        if any(k in _n for k in _PRICE_KEYS):
            anchor_y = _y if anchor_y is None else min(anchor_y, _y)
    original = None
    saved = None

    for i, (text, x, y, w, h) in enumerate(blocks):
        for kind, v, prio in _split_block(text):
            if kind == "price":
                if prio > price_prio:
                    price, price_prio, price_y = v, prio, y
            elif kind == "original" and original is None:
                original = v
            elif kind == "save" and saved is None:
                saved = v

    # 有价格标签但没读到金额的块，找邻居。
    # 按优先级选（「券后」比「折后价」更接近实付），同优先级取先出现的。
    if price is None:
        best = None   # (prio, v, y, j)
        for i, (text, x, y, w, h) in enumerate(blocks):
            t = _norm(text)
            prio = 0
            for level, keys in _PRICE_LABELS:
                if any(k in t for k in keys):
                    prio = max(prio, level)
            if not prio:
                continue
            found = _near_amount(blocks, i, used, allow_inline=False)
            if not found or not (0 < found[0] < 100000):
                continue
            if best is None or prio > best[0]:
                best = (prio, found[0], y, found[1])
        if best:
            price, price_y = best[1], best[2]
            used.add(best[3])

    # 优惠额：标签在但块内没金额时，同样找邻居
    if saved is None:
        for i, (text, x, y, w, h) in enumerate(blocks):
            t = _norm(text)
            if not any(k in t for k in _SAVE_KEYS):
                continue
            found = _near_amount(blocks, i, used, allow_inline=False)
            if found and 0 < found[0] < 100000:
                saved = found[0]
                used.add(found[1])
                break

    # 原价：没有原价标签时，用里现价最近、且比现价大的纯金额块兜底
    if original is None and price is not None:
        best = None
        best_dy = 1e18
        for j, (t2, x2, y2, w2, h2) in enumerate(blocks):
            if j in used:
                continue
            m = _AMOUNT_BLOCK.fullmatch(t2.strip())
            if not m:
                continue
            v = _clean_amount(m.group(1))
            if v is None or not (price < v < 100000):
                continue
            dy = abs(y2 - (price_y or y2)) if price_y is not None else 0
            if dy < best_dy:
                best_dy = dy
                best = (v, j)
        if best:
            original = best[0]
            used.add(best[1])

    # ── 算术自洽 ──
    derived = []
    if price is not None and saved is not None and price > 0:
        calc = round(price + saved, 2)
        if original is not None and abs(original - calc) > 0.5:
            result["suspicious"].append(
                f"原价 OCR 读成 {original:g}，但 现价+优惠 = {calc:g}，已按后者算"
            )
        original = calc
        derived.append("original")
    elif price is not None and original is not None:
        if original > price:
            saved = round(original - price, 2)
            derived.append("saved")
        else:
            result["suspicious"].append(
                f"原价 {original:g} 不比现价 {price:g} 高，可能读错了"
            )

    if price is not None:
        result["price"] = price
    if original is not None:
        result["original"] = original
    if saved is not None:
        result["saved"] = saved
    if derived:
        result["derived"] = derived

    merchant = _merchant_from_blocks(blocks, price_y)
    if merchant:
        result["merchant"] = merchant
    product = _product_from_blocks(blocks, anchor_y if anchor_y is not None else price_y)
    if product:
        result["product"] = product

    return result


# ──────────────────────────────────────────────────────────
# 按行解析（退路，用于纯文本）
# ──────────────────────────────────────────────────────────

def parse_product_page(text: str) -> dict:
    """从纯文本（OCR 输出或手工粘贴）里抽信息。

    这是没有坐标时的退路。有坐标请优先用 parse_product_blocks。
    """
    result: dict = {"suspicious": [], "raw_lines": []}
    if not text:
        return result

    lines = [_norm(l) for l in str(text).splitlines() if l.strip()]
    result["raw_lines"] = lines

    price = original = saved = None
    price_line = ""

    for line in lines:
        # 现价
        if price is None and (any(k in line for k in _PRICE_KEYS)
                              or ("价" in line and re.search(r"\d", line))):
            price_line = line
            v, why = _amount_from_line(line)
            if v is not None and 0 < v < 100000:
                price = v
            else:
                result["suspicious"].append(f"现价读不出来（{why}）：「{line}」")
            continue

        # 原价
        if original is None and any(k in line for k in _ORIGINAL_KEYS):
            v, why = _amount_from_line(line)
            if v is not None and 0 < v < 100000:
                original = v
            else:
                result["suspicious"].append(f"原价读不出来（{why}）：「{line}」")
            continue

        # 优惠额
        if saved is None and any(k in line for k in _SAVE_KEYS):
            v, why = _amount_from_line(line)
            if v is not None and 0 < v < 100000:
                saved = v
            else:
                result["suspicious"].append(f"优惠额读不出来（{why}）：「{line}」")
            continue

    # 原价回退：带 ¥、且比现价大的行（允许带「月售」）
    if original is None and price is not None:
        for line in lines:
            if line == price_line or "¥" not in line:
                continue
            v, _why = _amount_from_line(line)
            if v is not None and price < v < 100000:
                original = v
                break

    # ── 算术自洽（同坐标版）──
    derived = []
    if price is not None and saved is not None and price > 0:
        calc = round(price + saved, 2)
        if original is not None and abs(original - calc) > 0.5:
            result["suspicious"].append(
                f"原价 OCR 读成 {original:g}，但 现价+优惠 = {calc:g}，已按后者算"
            )
        original = calc
        derived.append("original")
    elif price is not None and original is not None:
        if original > price:
            saved = round(original - price, 2)
            derived.append("saved")
        else:
            result["suspicious"].append(
                f"原价 {original:g} 不比现价 {price:g} 高，可能读错了"
            )

    if price is not None:
        result["price"] = price
    if original is not None:
        result["original"] = original
    if saved is not None:
        result["saved"] = saved
    if derived:
        result["derived"] = derived

    # 商家名：价格行之前的短中文行
    if price_line:
        idx = lines.index(price_line)
        for line in reversed(lines[:idx]):
            plain = re.sub(r"[^\u4e00-\u9fa5A-Za-z]", "", line)
            han = len(re.findall(r"[\u4e00-\u9fa5]", plain))
            latin = len(re.findall(r"[A-Za-z]", plain))
            if not (han >= 3 or (han == 2 and latin == 0)):
                continue
            if 2 <= len(plain) <= 12:
                if any(k in plain for k in ("推荐", "评价", "商品", "描述",
                                            "购物车", "外卖", "查看", "首页")):
                    continue
                result["merchant"] = plain
                break

    # 商品名
    for line in lines:
        if _NOISE.search(line):
            continue
        plain = re.sub(r"\s+", "", line)
        if 3 <= len(plain) <= 40 and any(
            k in plain for k in ("蛋糕", "奶茶", "咖啡", "拿铁", "汉堡", "披萨",
                                 "套餐", "炸鸡", "寿司", "果汁", "鸡架", "小食",
                                 "桶", "青提", "玫瑰", "可乐", "饭", "面")
        ):
            result["product"] = plain
            break

    return result


# ──────────────────────────────────────────────────────────
# 输出
# ──────────────────────────────────────────────────────────

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
        bits.append(f"优惠 {info['saved']:g}")

    s = " | ".join(bits) if bits else "没认出有效信息"
    if info.get("suspicious"):
        s += "\n可能有问题：" + "；".join(info["suspicious"])
    return s


def parse_product_image(path) -> dict:
    """一步到位：图片 → 解析结果。有坐标用坐标，没有退回按行。"""
    blocks = ocr_blocks(path)
    if blocks:
        return parse_product_blocks(blocks)
    from .receipt import ocr_image

    return parse_product_page(ocr_image(path))
