"""生成优惠券页面（单文件 HTML，手机优先）。

两种用法：
  1. 静态导出 —— 生成一个 .html 文件，双击就能看。GitHub Pages 用的就是这个。
  2. 本地服务 —— server.py 调用 render(..., refresh_url="/refresh")，
     页面上会多出一个「刷新」按钮，点一下让服务端重新抓券。

安全提示：券的标题、口令、链接全部来自第三方接口，属于**不可信输入**。
所以这里做了两件事，改代码时别把它们去掉：
  1. 所有插入 HTML 的文本都过 html.escape；
  2. 链接只允许 http/https，挡掉 javascript: / data: 这类伪协议。
"""

from __future__ import annotations

import html
from datetime import datetime

from .models import Coupon

_ALLOWED_SCHEMES = ("http://", "https://")


def _safe_url(url: str) -> str:
    """只放行 http/https。挡掉 javascript:、data:、file: 等伪协议。"""
    if not url:
        return ""
    low = url.strip().lower()
    if low.startswith(_ALLOWED_SCHEMES):
        return url.strip()
    return ""


def _card(c: Coupon, idx: int) -> str:
    title = html.escape(c.title)
    code = html.escape(c.code)
    guideline = html.escape(c.guideline)
    url = html.escape(_safe_url(c.url))
    discount = html.escape(c.discount_text())

    tag_cls = {
        "官方直发": "official",
        "口令券": "code",
        "会场": "venue",
        "扫码会场": "venue",
    }.get(c.tag, "code")

    code_block = ""
    if c.code:
        # data-code 用 html.escape(quote=True) 单独转义，避免中文引号破坏属性
        code_block = f"""
        <div class="code-row">
          <code class="code-text" data-code="{html.escape(c.code, quote=True)}">{code}</code>
          <button class="copy-btn" type="button">复制</button>
        </div>"""

    link_block = ""
    if url and not url.lower().endswith((".jpg", ".png", ".jpeg")):
        link_block = f'<a class="link" href="{url}" target="_blank" rel="noopener noreferrer">打开链接 →</a>'
    elif url:
        link_block = f'<a class="link" href="{url}" target="_blank" rel="noopener noreferrer">查看二维码 →</a>'

    valid = f'<span class="valid">有效期至 {html.escape(c.valid_to)}</span>' if c.valid_to else ""
    guide = f'<div class="guide">{guideline}</div>' if guideline else ""

    # 平台名放到 data 属性上，供前端筛选用（已转义）
    plat = html.escape(c.platform, quote=True)

    return f"""
  <article class="card" data-platform="{plat}">
    <div class="rank">{idx}</div>
    <div class="body">
      <h2 class="title">{title}</h2>
      <div class="meta">
        <span class="badge {tag_cls}">{html.escape(c.tag)}</span>
        <span class="plat">{html.escape(c.platform)}</span>
        <span class="discount">{discount}</span>
        {valid}
      </div>
      {code_block}
      {link_block}
      {guide}
    </div>
  </article>"""


def render(
    coupons: list[Coupon],
    result=None,
    *,
    title: str = "优惠猎手",
    refresh_url: str = "",
    note: str = "",
    source_note: str = "",
) -> str:
    """把券列表渲染成一个完整网页。

    refresh_url 非空时会在页面上加「刷新」按钮（只有本地服务模式才用得上）。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cards = "\n".join(_card(c, i) for i, c in enumerate(coupons, 1))

    if not coupons:
        cards = '<div class="empty">这次一张券都没抓到。<br>可能是接口临时抽风，过会儿点右上角刷新试试。</div>'

    # 平台统计，用来生成筛选按钮
    counts: dict[str, int] = {}
    for c in coupons:
        counts[c.platform] = counts.get(c.platform, 0) + 1

    chips = [f'<button class="chip on" type="button" data-f="__all__">全部 {len(coupons)}</button>']
    for plat, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        chips.append(
            f'<button class="chip" type="button" data-f="{html.escape(plat, quote=True)}">'
            f"{html.escape(plat)} {n}</button>"
        )
    chips_html = "\n      ".join(chips)

    # 数据源状态（本地模式显示，GitHub Pages 上留空）
    status_html = ""
    if result is not None:
        items = []
        for e in getattr(result, "errors", []):
            items.append(f'<li class="err">{html.escape(e)}</li>')
        for n in getattr(result, "notes", []):
            items.append(f"<li>{html.escape(n)}</li>")
        if items:
            status_html = '<ul class="notes">' + "".join(items) + "</ul>"

    refresh_btn = (
        f'<button class="refresh" type="button" id="refreshBtn">刷新</button>'
        if refresh_url
        else ""
    )

    top_note = f'<div class="sub note">{html.escape(note)}</div>' if note else ""
    src_note = f'<div class="sub">{html.escape(source_note)}</div>' if source_note else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0f1115">
<meta name="color-scheme" content="dark light">
<title>{html.escape(title)} · {now}</title>
<style>
  :root {{
    --bg:#0f1115; --card:#181b22; --card2:#1f232c; --line:#282d38;
    --text:#e8eaed; --dim:#9aa0aa; --accent:#ffd60a; --green:#34c759; --blue:#4da3ff;
    --safe-top: env(safe-area-inset-top, 0px);
    --safe-bottom: env(safe-area-inset-bottom, 0px);
  }}
  @media (prefers-color-scheme: light) {{
    :root {{ --bg:#f2f3f5; --card:#fff; --card2:#f7f8fa; --line:#e3e5e9;
             --text:#1c1e21; --dim:#6b7280; --accent:#c98a00; --green:#1a9e46; --blue:#0b6bd6; }}
  }}
  * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
  html {{ -webkit-text-size-adjust: 100%; }}
  body {{
    margin:0; background:var(--bg); color:var(--text);
    font:16px/1.55 -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
    padding-bottom: calc(28px + var(--safe-bottom));
  }}

  /* ── 顶部：吸顶，手机上一眼看到筛选 ──
     刻意不用 backdrop-filter 毛玻璃效果：它会让部分浏览器和自动化工具的
     可点击性判定失效（实测 Playwright 点不动筛选按钮），而且在中低端安卓上
     滚动会掉帧。纯色背景更稳也更快。 */
  header {{
    position: sticky; top:0; z-index:10;
    background: var(--bg);
    border-bottom: 1px solid var(--line);
    padding-top: var(--safe-top);
  }}
  .head-top {{
    max-width: 860px; margin: 0 auto;
    padding: 14px 16px 0; display:flex; align-items:flex-start; gap:12px;
  }}
  .head-top h1 {{ font-size: 19px; margin:0 0 3px; letter-spacing:.2px; }}
  .sub {{ color: var(--dim); font-size: 12.5px; }}
  .note {{ color: var(--accent); }}
  .refresh {{
    margin-left:auto; flex:none;
    background: var(--card2); color: var(--text);
    border:1px solid var(--line); border-radius: 10px;
    padding: 10px 15px; font-size: 14px; font-weight:600;
    min-height: 44px; cursor:pointer;
  }}
  .refresh:active {{ transform: scale(.96); }}
  .refresh.busy {{ color: var(--dim); }}

  /* ── 筛选条：手机上横向滚动，不换行 ── */
  .chips {{
    max-width: 860px; margin: 0 auto;
    display:flex; gap:8px; overflow-x:auto; scrollbar-width:none;
    padding: 12px 16px 13px;
  }}
  .chips::-webkit-scrollbar {{ display:none; }}
  .chip {{
    flex:none; background: var(--card); color: var(--dim);
    border:1px solid var(--line); border-radius: 999px;
    padding: 8px 15px; font-size: 13.5px; font-weight:600;
    min-height: 38px; cursor:pointer; white-space:nowrap;
  }}
  .chip.on {{ background: var(--text); color: var(--bg); border-color: var(--text); }}

  main {{ max-width: 860px; margin: 0 auto; padding: 16px 16px 0; }}

  .card {{
    display:flex; gap:12px;
    background: var(--card); border:1px solid var(--line);
    border-radius: 16px; padding: 15px; margin-bottom: 12px;
  }}
  .card[hidden] {{ display:none; }}
  .rank {{ color: var(--dim); font-weight:700; font-size:14px; min-width:26px; padding-top:2px; }}
  .body {{ flex:1; min-width:0; }}
  .title {{ font-weight:600; font-size:16px; margin:0 0 8px; word-break: break-word; line-height:1.4; }}
  .meta {{ display:flex; flex-wrap:wrap; gap:7px; align-items:center; font-size:12.5px; margin-bottom:10px; }}
  .badge {{ padding: 3px 9px; border-radius: 999px; font-weight:600; font-size:11.5px; }}
  .badge.official {{ background: rgba(52,199,89,.16); color: var(--green); }}
  .badge.code {{ background: rgba(77,163,255,.16); color: var(--blue); }}
  .badge.venue {{ background: rgba(255,214,10,.16); color: var(--accent); }}
  .plat, .valid {{ color: var(--dim); }}
  .discount {{ color: var(--accent); font-weight:700; }}

  /* ── 口令：手机上换行显示 + 右侧大按钮 ── */
  .code-row {{ display:flex; gap:8px; align-items:stretch; margin: 10px 0 4px; }}
  .code-text {{
    flex:1; min-width:0; background: var(--bg);
    border:1px dashed var(--line); border-radius: 10px;
    padding: 11px 12px; font-size: 13px; line-height:1.5;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    word-break: break-all; overflow-wrap: anywhere;
    -webkit-user-select: all; user-select: all;
  }}
  .copy-btn {{
    flex:none; min-width: 74px; background: var(--blue); color:#fff;
    border:none; border-radius: 10px; font-size: 14px; font-weight:700;
    cursor:pointer; padding: 0 14px;
  }}
  .copy-btn:active {{ transform: scale(.96); }}
  .copy-btn.done {{ background: var(--green); }}
  .link {{ color: var(--blue); font-size: 13.5px; text-decoration:none; display:inline-block;
           padding: 7px 0; font-weight:600; }}
  .guide {{ color: var(--dim); font-size: 12.5px; margin-top: 7px; }}

  .notes {{ list-style:none; padding: 14px 16px; margin: 4px 0 0;
            background: var(--card); border:1px solid var(--line);
            border-radius: 14px; font-size: 13px; color: var(--dim); }}
  .notes .err {{ color: #ff6b6b; }}
  .empty {{ text-align:center; color: var(--dim); padding: 70px 20px; line-height:1.9; }}

  .toast {{
    position: fixed; left:50%; bottom: calc(26px + var(--safe-bottom));
    transform: translateX(-50%) translateY(16px);
    background: var(--green); color:#fff; padding: 11px 22px;
    border-radius: 999px; font-size: 14px; font-weight:600;
    opacity:0; transition: all .2s; pointer-events:none; z-index:50;
  }}
  .toast.on {{ opacity:1; transform: translateX(-50%) translateY(0); }}

  /* 窄屏再压一点留白，别浪费手机屏幕 */
  @media (max-width: 420px) {{
    .head-top, .chips, main {{ padding-left: 13px; padding-right: 13px; }}
    .card {{ padding: 13px; border-radius: 14px; }}
    .title {{ font-size: 15.5px; }}
    .copy-btn {{ min-width: 64px; padding: 0 11px; }}
  }}
</style>
</head>
<body>
<header>
  <div class="head-top">
    <div>
      <h1>{html.escape(title)}</h1>
      <div class="sub">更新于 {now} · 共 {len(coupons)} 条</div>
      {src_note}
      {top_note}
    </div>
    {refresh_btn}
  </div>
  <div class="chips">
      {chips_html}
  </div>
</header>

<main>
{cards}
{status_html}
</main>

<div class="toast" id="toast">已复制</div>

<script>
(function () {{
  "use strict";

  /* ── 复制口令 ──
     注意：通过 http://192.168.x.x 访问时不是「安全上下文」，
     navigator.clipboard 根本不存在，所以必须保留 execCommand 兜底。 */
  function copyText(text) {{
    if (navigator.clipboard && window.isSecureContext) {{
      return navigator.clipboard.writeText(text);
    }}
    return new Promise(function (resolve, reject) {{
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      ta.setSelectionRange(0, text.length);
      var ok = false;
      try {{ ok = document.execCommand('copy'); }} catch (e) {{ ok = false; }}
      document.body.removeChild(ta);
      ok ? resolve() : reject(new Error('execCommand failed'));
    }});
  }}

  function toast(msg) {{
    var t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('on');
    clearTimeout(t._timer);
    t._timer = setTimeout(function () {{ t.classList.remove('on'); }}, 1500);
  }}

  document.addEventListener('click', function (ev) {{
    var btn = ev.target.closest('.copy-btn');
    if (!btn) return;
    var codeEl = btn.parentElement.querySelector('.code-text');
    var text = codeEl.dataset.code;

    copyText(text).then(function () {{
      btn.textContent = '已复制 ✓';
      btn.classList.add('done');
      toast('已复制，去 App 粘贴');
      setTimeout(function () {{
        btn.textContent = '复制';
        btn.classList.remove('done');
      }}, 2000);
    }}).catch(function () {{
      // 复制不了就把文字选中，让用户长按手动复制
      var r = document.createRange();
      r.selectNodeContents(codeEl);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
      toast('请长按选中的文字复制');
    }});
  }});

  /* ── 平台筛选（纯前端，不请求服务器） ── */
  var chips = document.querySelectorAll('.chip');
  var cards = document.querySelectorAll('.card');
  Array.prototype.forEach.call(chips, function (chip) {{
    chip.addEventListener('click', function () {{
      Array.prototype.forEach.call(chips, function (c) {{ c.classList.remove('on'); }});
      chip.classList.add('on');
      var f = chip.dataset.f;
      Array.prototype.forEach.call(cards, function (card) {{
        card.hidden = (f !== '__all__' && card.dataset.platform !== f);
      }});
    }});
  }});

  /* ── 刷新（只有本地服务模式才有这个按钮） ── */
  var refreshBtn = document.getElementById('refreshBtn');
  if (refreshBtn) {{
    refreshBtn.addEventListener('click', function () {{
      refreshBtn.disabled = true;
      refreshBtn.textContent = '抓取中…';
      refreshBtn.classList.add('busy');
      fetch({refresh_url!r}, {{ cache: 'no-store' }})
        .then(function (r) {{ return r.json(); }})
        .then(function () {{ location.reload(); }})
        .catch(function () {{
          refreshBtn.disabled = false;
          refreshBtn.textContent = '刷新';
          refreshBtn.classList.remove('busy');
          toast('刷新失败，检查网络');
        }});
    }});
  }}
}})();
</script>
</body>
</html>"""
