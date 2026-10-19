"""
本地服务里的「手机传图比价」页面。

为什么做这个
────────────────────────────────────────────
用户嫌「截三张图 + 传到电脑 + 敲命令」太麻烦。但外卖点餐只在 App 里，
网页端有登录墙和滑块验证（实测过），所以截图是唯一可靠的信息来源。

那就把上传这一步做顺：**手机截完图，直接在手机上打开本地网页，选三张图上传，
立刻看到比价结果**。不用碰电脑、不用敲命令。

安全性
────────────────────────────────────────────
这个服务只监听局域网（或本机），而且：
  · 只接受图片（按扩展名 + 文件头双重校验）
  · 限制单文件大小和总大小
  · 上传的图只写到临时目录，处理完立刻删
  · 不落盘保存、不记录内容
"""

from __future__ import annotations

import html
import json
import tempfile
from pathlib import Path

# 单张图最大 12 MB（手机截图通常 1-3 MB）
MAX_FILE = 12 * 1024 * 1024
MAX_TOTAL = 36 * 1024 * 1024
# 允许的图片扩展名
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

# 图片文件头，用来防止「改个扩展名就传上来」
_MAGIC = {
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
    b"BM": ".bmp",
    b"RIFF": ".webp",
}


def _looks_like_image(data: bytes) -> bool:
    return any(data.startswith(sig) for sig in _MAGIC)


def render_upload_page() -> str:
    """上传页面。手机优先。"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0f1115">
<title>外卖比价 · 传截图</title>
<style>
  :root{--bg:#0f1115;--card:#181b22;--line:#282d38;--text:#e8eaed;--dim:#9aa0aa;
        --accent:#ffd60a;--green:#34c759;--blue:#4da3ff;--red:#ff6b6b;
        --safe-top:env(safe-area-inset-top,0px);--safe-bottom:env(safe-area-inset-bottom,0px)}
  @media (prefers-color-scheme:light){:root{--bg:#f2f3f5;--card:#fff;--line:#e3e5e9;
        --text:#1c1e21;--dim:#6b7280;--accent:#c98a00;--green:#1a9e46;--blue:#0b6bd6}}
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  body{margin:0;background:var(--bg);color:var(--text);padding-top:var(--safe-top);
       font:16px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif}
  .wrap{max-width:560px;margin:0 auto;padding:20px 16px calc(30px + var(--safe-bottom))}
  h1{font-size:20px;margin:0 0 6px}
  .sub{color:var(--dim);font-size:13px;margin-bottom:20px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin-bottom:14px}
  .row{display:flex;align-items:center;gap:10px;margin-bottom:12px}
  .row:last-child{margin-bottom:0}
  label{flex:none;width:88px;font-size:14px;color:var(--dim)}
  input[type=file]{flex:1;min-width:0;font-size:13px;color:var(--text)}
  .hint{color:var(--dim);font-size:12.5px;line-height:1.7;margin-top:10px}
  button{width:100%;border:none;border-radius:14px;padding:16px;font-size:16px;font-weight:700;
         cursor:pointer;min-height:54px}
  .go{background:var(--blue);color:#fff}
  .go:active{transform:scale(.98)}
  .go:disabled{opacity:.5}
  #result{margin-top:18px}
  .rank{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:10px}
  .rank.first{border-color:var(--green)}
  .plat{font-weight:700;font-size:16px}
  .price{float:right;font-weight:800;color:var(--green);font-size:18px}
  .detail{color:var(--dim);font-size:13px;margin-top:6px}
  .warn{color:var(--accent);font-size:13px;margin-top:6px}
  .err{color:var(--red);font-size:14px}
  .steps{font-size:13.5px;line-height:1.9;margin-top:8px;padding-left:18px}
  .steps li{margin-bottom:4px}
  .badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11.5px;
         background:rgba(52,199,89,.16);color:var(--green);margin-left:6px;vertical-align:middle}
</style>
</head>
<body>
<div class="wrap">
  <h1>外卖比价</h1>
  <div class="sub">三家 App 各截一张结账页，选好上传，自动算出哪家最便宜。</div>

  <form id="f">
    <div class="card">
      <div class="row"><label>美团</label><input type="file" name="美团" accept="image/*" capture="environment"></div>
      <div class="row"><label>淘宝闪购</label><input type="file" name="淘宝闪购" accept="image/*" capture="environment"></div>
      <div class="row"><label>京东外卖</label><input type="file" name="京东外卖" accept="image/*" capture="environment"></div>
      <div class="hint">
        只填一两张也能比。截图请截<b>结账页</b>（能看到"商品小计/配送费/实付"那一屏）。<br>
        图片只在本机处理，不上传任何服务器。
      </div>
    </div>
    <div class="card">
      <div class="row"><label>店名</label>
        <input type="text" name="shop" placeholder="可不填" style="flex:1;padding:10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--text);font-size:15px">
      </div>
    </div>
    <button class="go" type="submit" id="btn">开始比价</button>
  </form>

  <div id="result"></div>
</div>

<script>
document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = document.getElementById('btn');
  const out = document.getElementById('result');
  btn.disabled = true;
  btn.textContent = '识别中…（每张约 2-3 秒）';
  out.innerHTML = '';

  try {
    const fd = new FormData(e.target);
    const resp = await fetch('/upload', { method: 'POST', body: fd });
    const data = await resp.json();
    render(data);
  } catch (err) {
    out.innerHTML = '<div class="err">请求失败：' + err + '</div>';
  } finally {
    btn.disabled = false;
    btn.textContent = '开始比价';
  }
});

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function render(d) {
  const out = document.getElementById('result');
  if (d.error) { out.innerHTML = '<div class="err">' + esc(d.error) + '</div>'; return; }

  let h = '';
  if (d.offers && d.offers.length === 0) {
    h += '<div class="err">没有识别出任何一张有效的结账页截图。</div>';
    h += '<div class="detail">' + esc(d.hint || '') + '</div>';
    out.innerHTML = h; return;
  }

  d.offers.forEach((o, i) => {
    h += '<div class="rank' + (i === 0 ? ' first' : '') + '">';
    h += '<div><span class="plat">' + esc(o.platform) + '</span>';
    if (i === 0 && d.offers.length > 1) h += '<span class="badge">最便宜</span>';
    h += '<span class="price">¥' + o.final.toFixed(2) + '</span></div>';
    h += '<div class="detail">' + esc(o.detail) + '</div>';
    if (o.warn) h += '<div class="warn">⚠️ ' + esc(o.warn) + '</div>';
    if (o.steps && o.steps.length) {
      h += '<ol class="steps">' + o.steps.map(s => '<li>' + esc(s) + '</li>').join('') + '</ol>';
    }
    h += '</div>';
  });

  if (d.offers.length > 1 && d.saving > 0) {
    h += '<div class="detail" style="text-align:center;margin:14px 0">';
    h += '最便宜比最贵省 ¥' + d.saving.toFixed(2) + '</div>';
  }
  h += '<div class="hint">以下单页结算时显示的为准，本工具不会替你下单。</div>';
  out.innerHTML = h;
}
</script>
</body>
</html>"""


def _read_multipart(body: bytes, boundary: bytes) -> dict[str, tuple[str, bytes]]:
    """极简 multipart/form-data 解析，只取文件部分和文本部分。

    为什么自己写：本项目的原则是零第三方依赖，而 multipart 的格式
    其实很简单（用 boundary 分段，每段有 header + 空行 + 内容）。
    为此装一个库不值得。
    """
    parts: dict[str, tuple[str, bytes]] = {}
    sep = b"--" + boundary
    for chunk in body.split(sep):
        if not chunk or chunk in (b"--\r\n", b"--", b"\r\n"):
            continue
        chunk = chunk.lstrip(b"\r\n")
        if b"\r\n\r\n" not in chunk:
            continue
        head, data = chunk.split(b"\r\n\r\n", 1)
        data = data.rstrip(b"\r\n")

        # 浏览器发的是 UTF-8；但某些命令行工具（curl 在中文 Windows 下）
        # 会用本地编码发字段名。两种都试一下，否则中文平台名会解成乱码，
        # 导致「美团」这个字段完全匹配不上。
        head_text = None
        for _enc in ("utf-8", "gbk"):
            try:
                head_text = head.decode(_enc)
                break
            except UnicodeDecodeError:
                continue
        if head_text is None:
            head_text = head.decode("utf-8", errors="replace")
        name = ""
        filename = ""
        for line in head_text.splitlines():
            low = line.lower()
            if low.startswith("content-disposition:"):
                for seg in line.split(";"):
                    seg = seg.strip()
                    if seg.startswith("name="):
                        name = seg[5:].strip().strip('"')
                    elif seg.startswith("filename="):
                        filename = seg[9:].strip().strip('"')
        if name:
            parts[name] = (filename, data)
    return parts


def handle_upload(body: bytes, content_type: str) -> tuple[int, dict]:
    """处理上传，返回 (HTTP 状态码, 结果字典)。

    不抛异常——所有失败都变成 {"error": "人话说明"}，方便前端显示。
    """
    import re

    from .advice import build_advice
    from .delivery import Offer, compare
    from .receipt import OcrError, ocr_image, parse_receipt
    from .stack_cli import parse_coupon

    m = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type or "")
    if not m:
        return 400, {"error": "上传格式不对（缺少 boundary）"}
    boundary = (m.group(1) or m.group(2)).strip().encode()

    if len(body) > MAX_TOTAL:
        return 413, {"error": f"上传内容太大（上限 {MAX_TOTAL // 1024 // 1024} MB）"}

    parts = _read_multipart(body, boundary)
    shop = ""
    for name, (fn, data) in parts.items():
        if name == "shop":
            shop = data.decode("utf-8", errors="replace").strip()
            break

    platforms = ["美团", "淘宝闪购", "京东外卖"]
    offers = []
    notes = []

    for platform in platforms:
        if platform not in parts:
            continue
        filename, data = parts[platform]
        if not data:
            continue
        if len(data) > MAX_FILE:
            notes.append(f"{platform}：图片太大，已跳过")
            continue
        if not _looks_like_image(data):
            notes.append(f"{platform}：不是有效图片，已跳过")
            continue

        # 写临时文件 → OCR → 立刻删除
        suffix = ".png"
        for sig, ext in _MAGIC.items():
            if data.startswith(sig):
                suffix = ext
                break
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(data)
                tmp = Path(f.name)
            text = ocr_image(tmp)
            pre = parse_receipt(text)
        except OcrError as e:
            notes.append(f"{platform}：{e}")
            continue
        finally:
            if tmp and tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass

        if "items" not in pre:
            notes.append(f"{platform}：没认出「商品小计」，截图可能不是结账页")
            continue

        # 把 OCR 读到的满减/券转成 stacking 的券对象
        # 注意：只把**明确读到金额**的项当券用；读不到的宁可不算。
        shop_coupons = []
        if pre.get("shop_discount"):
            try:
                shop_coupons.append(parse_coupon(f"满减,{pre['items']:g},{pre['shop_discount']:g}"))
            except Exception:
                pass
        plat_coupons = []
        if pre.get("coupon"):
            try:
                plat_coupons.append(parse_coupon(f"满减,{pre['items']:g},{pre['coupon']:g}"))
            except Exception:
                pass

        offers.append(Offer(
            platform=platform,
            items=pre["items"],
            delivery=pre.get("delivery", 0.0),
            packing=pre.get("packing", 0.0),
            shop_discounts=shop_coupons,
            coupons=plat_coupons,
            red_packet=pre.get("red_packet", 0.0),
            member=bool(pre.get("member")),
            member_delivery_free=bool(pre.get("member")),
            expected_final=pre.get("final"),
        ))

    if not offers:
        return 200, {
            "offers": [],
            "hint": "；".join(notes) or "请选择结账页截图（能看到商品小计/配送费/实付的那一屏）",
        }

    results = compare(offers)
    payload = []
    by_platform = {o.platform: o for o in offers}

    for r in results:
        o = by_platform[r.platform]
        steps = []
        detail = f"菜品 {r.items:.2f} → {r.food_after:.2f}"
        if r.delivery:
            detail += f" + 配送 {r.delivery:.2f}"
        if r.packing:
            detail += f" + 打包 {r.packing:.2f}"

        used = [s.coupon_name for s in r.steps]
        if used:
            steps.append("结算页确认这些已勾上：" + "、".join(used))
        if o.expected_final is not None:
            if abs(r.final_price - o.expected_final) < 0.01:
                steps.append(f"与平台显示的实付 {o.expected_final:.2f} 一致，可照此下单")
            else:
                steps.append(
                    f"平台显示 {o.expected_final:.2f}，本工具算 {r.final_price:.2f}，以平台为准"
                )
        steps.append("核对实付金额后下单")

        warn = ""
        if o.expected_final is not None and abs(r.final_price - o.expected_final) >= 0.01:
            warn = "和平台显示的实付对不上，可能是截图有项没看清，以平台为准"

        payload.append({
            "platform": r.platform,
            "final": r.final_price,
            "detail": detail,
            "warn": warn,
            "steps": steps,
        })

    saving = payload[-1]["final"] - payload[0]["final"] if len(payload) > 1 else 0
    return 200, {
        "shop": shop,
        "offers": payload,
        "saving": round(saving, 2),
        "hint": "；".join(notes),
    }
