"""
「菜单抓取」页面 —— 本地服务里的一个页面，手机也能开。

两条路并排放，因为它们的风险性质不一样，让用户自己选：

  ① 内置浏览器（一键抓）
     点开浏览器 → 你自己登录一次 → 点进店铺页 → 点「抓取当前页」
     代价：**工具持有你的登录态**（存在 data/browser-profile/）
     好处：不用装插件、不用复制粘贴

  ② 粘贴（脚本或手打）
     浏览器脚本复制一段文本 → 粘进框里 → 点「解析」
     代价：要装个油猴脚本，或者自己敲
     好处：**工具只拿到一段文字，永远碰不到你的登录态**

为什么不合并成一条：这两件事不可能同时成立。
要"自动"就得让程序带着你的身份去访问；要"程序不带你的身份"，
那这一步只能由你完成。我选择把它们摆在明面上，而不是替你做取舍。
"""

from __future__ import annotations

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0f1115">
<title>菜单抓取 · 大全网</title>
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
  .sub{color:var(--dim);font-size:13px;margin-bottom:18px}
  .sub a{color:var(--blue);text-decoration:none}
  .card{background:var(--card);border:1px solid var(--line);border-radius:16px;
        padding:16px;margin-bottom:14px}
  .card h2{font-size:15px;margin:0 0 4px;display:flex;align-items:center;gap:8px}
  .tag{font-size:11px;padding:2px 8px;border-radius:20px;font-weight:600}
  .tag.safe{background:rgba(52,199,89,.16);color:var(--green)}
  .tag.risk{background:rgba(255,214,10,.16);color:var(--accent)}
  .note{color:var(--dim);font-size:12.5px;line-height:1.7;margin:8px 0 12px}
  .btns{display:flex;gap:8px;flex-wrap:wrap}
  button{border:none;border-radius:12px;padding:12px 14px;font-size:14px;font-weight:700;
         cursor:pointer;min-height:46px;background:var(--line);color:var(--text)}
  button:active{transform:scale(.98)}
  button:disabled{opacity:.45;cursor:default}
  button.primary{background:var(--blue);color:#fff;flex:1}
  button.go{background:var(--green);color:#fff;flex:1}
  button.ghost{background:transparent;border:1px solid var(--line);color:var(--dim)}
  input,textarea{width:100%;background:var(--bg);border:1px solid var(--line);
        border-radius:12px;color:var(--text);padding:12px;font-size:14px;
        font-family:inherit;margin-bottom:10px}
  textarea{min-height:110px;font-family:Consolas,Menlo,monospace;font-size:12.5px}
  #status{font-size:13px;color:var(--dim);margin:10px 0 0;word-break:break-all}
  #status.ok{color:var(--green)}
  #status.bad{color:var(--red)}
  #status.warn{color:var(--accent)}
  #out{margin-top:4px}
  .sum{font-size:15px;font-weight:700;margin:0 0 4px}
  .sum small{font-weight:400;color:var(--dim);font-size:12.5px}
  .dish{display:flex;justify-content:space-between;gap:10px;padding:7px 0;
        border-bottom:1px solid var(--line);font-size:14px}
  .dish:last-child{border-bottom:none}
  .dish .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .dish .p{flex:none;color:var(--green);font-weight:600}
  .dish .p s{color:var(--dim);font-weight:400;margin-left:6px;font-size:12px}
  .total{display:flex;justify-content:space-between;padding-top:10px;margin-top:6px;
         border-top:2px solid var(--line);font-weight:800}
  .spec{background:var(--bg);border:1px dashed var(--line);border-radius:10px;
        padding:10px;margin-top:12px;font-family:Consolas,Menlo,monospace;
        font-size:12.5px;word-break:break-all}
  .warnbox{color:var(--dim);font-size:12px;line-height:1.7;margin-top:10px}
  .empty{color:var(--dim);font-size:13.5px;padding:10px 0}
</style>
</head>
<body>
<div class="wrap">
  <h1>菜单抓取</h1>
  <div class="sub">把店里点了什么、多少钱读出来，最后和券、配送费一起算总价。
    <a href="/upload">去外卖比价 →</a></div>

  <div class="card">
    <h2>① 内置浏览器 <span class="tag risk">会用到登录态</span></h2>
    <div class="note">
      点开一个真实 Chrome 窗口，你自己登录一次（只需一次）。之后点进任何一家店，
      回来点「抓取当前页」就行，不用装插件、不用复制粘贴。
      <br>代价：登录态存在本机 <code>data/browser-profile/</code>，等于工具拿着你的账号。
    </div>
    <input id="kw" placeholder="可选：直接在浏览器里搜索某个店（如 麦当劳）">
    <div class="btns">
      <button class="primary" onclick="openBrowser('美团')">打开美团</button>
      <button class="primary" onclick="openBrowser('淘宝闪购')">打开淘宝闪购</button>
    </div>
    <div class="btns" style="margin-top:8px">
      <button class="go" id="btnGrab" onclick="grab()">抓取当前页</button>
      <button class="ghost" onclick="closeBrowser()">关闭浏览器</button>
    </div>
    <div id="status"></div>
  </div>

  <div class="card">
    <h2>② 粘贴解析 <span class="tag safe">不碰登录态</span></h2>
    <div class="note">
      用浏览器脚本把当前页复制下来，粘到下面这个框里。工具只拿到这段文字，
      <b>永远不会碰到你的 cookie</b>。没有脚本也可以手打，一行一项：
      <code>菜名&nbsp;&nbsp;价格</code>。
    </div>
    <textarea id="raw" placeholder="麦辣鸡腿堡&#9;12.9&#10;板烧鸡腿堡&#9;13.9"></textarea>
    <div class="btns">
      <button class="primary" onclick="parsePaste()">解析这段文本</button>
    </div>
  </div>

  <div id="out"></div>
</div>

<script>
const $ = (id) => document.getElementById(id);

function setStatus(text, kind){
  const el = $('status');
  el.textContent = text || '';
  el.className = kind || '';
}

function esc(s){
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function money(v){
  return '¥' + Number(v || 0).toFixed(2);
}

// 「淘宝闪购/饿了么」这种东西没法直接塞进 <select>，统一成可选值
function platformForSelect(source){
  const s = String(source || '');
  if (s.indexOf('美团') >= 0) return '美团';
  if (s.indexOf('饿了么') >= 0 || s.indexOf('淘宝') >= 0) return '淘宝闪购';
  if (s.indexOf('京东') >= 0) return '京东外卖';
  return '美团';
}

function render(data){
  const out = $('out');
  if (!data || data.ok === false){
    out.innerHTML = '<div class="card"><div class="empty">'
      + esc((data && data.error) || '没拿到结果') + '</div></div>';
    return;
  }

  const dishes = data.dishes || [];
  if (!dishes.length){
    let html = '<div class="card"><div class="empty">没从这一页认出菜品。</div>';
    (data.notes || []).forEach(function(n){
      html += '<div class="warnbox">· ' + esc(n) + '</div>';
    });
    html += '<div class="warnbox">如果这一页确实有菜单，把页面上看到的文字告诉我，我按真实版式改解析。</div>';
    html += '</div>';
    out.innerHTML = html;
    return;
  }

  let head = '<div class="card">';
  head += '<div class="sum">' + esc(data.store || '（没读到店名）');
  if (data.source) head += ' <small>' + esc(data.source) + '</small>';
  head += '</div>';
  head += '<div class="sum"><small>共 ' + dishes.length + ' 项</small></div>';

  let rows = '';
  dishes.forEach(function(d){
    rows += '<div class="dish"><span class="n">' + esc(d.name) + '</span>'
         +  '<span class="p">' + money(d.price)
         +  (d.original ? '<s>' + money(d.original) + '</s>' : '')
         +  '</span></div>';
  });

  let total = '<div class="total"><span>合计</span><span>' + money(data.total) + '</span></div>';
  if (data.original_total && data.original_total > data.total){
    total += '<div class="warnbox">按原价是 ' + money(data.original_total)
          +  '，标价上已省 ' + money(data.original_total - data.total) + '</div>';
  }

  let spec = '';
  if (data.offer_spec){
    spec = '<div class="spec">拿去比价：' + esc(data.offer_spec) + '</div>';
  }

  // 顺带读到的店铺优惠，以及去「最高折扣」的入口
  let promoBox = '';
  const sp = data.store_promos || [];
  if (sp.length){
    promoBox += '<div class="warnbox" style="margin-top:12px">'
      + '这一页还读到了店铺优惠：<b>'
      + sp.map(function(p){ return esc(p.describe || p.text); }).join('、')
      + '</b></div>';
  }

  let toDiscount = '<div class="spec">'
    + '<a class="link" style="color:var(--blue);text-decoration:none" href="/discount?'
    + 'platform=' + encodeURIComponent(platformForSelect(data.source))
    + '&items=' + encodeURIComponent(Number(data.total || 0).toFixed(2))
    + '">去算最高折扣（叠加平台券）→</a></div>';

  let notes = '';
  (data.notes || []).forEach(function(n){
    notes += '<div class="warnbox">· ' + esc(n) + '</div>';
  });

  head += rows + total + spec + promoBox + toDiscount + notes + '</div>';
  out.innerHTML = head;
}

async function getJSON(url){
  const r = await fetch(url, {cache:'no-store'});
  return await r.json();
}

async function openBrowser(platform){
  const kw = $('kw').value.trim();
  setStatus('正在打开浏览器……（首次会弹出一个 Chrome 窗口）', 'warn');
  const q = new URLSearchParams({platform: platform});
  if (kw) q.set('keyword', kw);
  try {
    const d = await getJSON('/api/menu/open?' + q.toString());
    if (!d.ok){ setStatus('✗ ' + (d.error || '打开失败'), 'bad'); return; }
    setStatus('✓ 已打开：' + (d.title || d.url) + '\\n'
      + '请在浏览器窗口里登录 / 点进店铺页，然后点「抓取当前页」。', 'ok');
  } catch(e){
    setStatus('✗ 请求失败：' + e, 'bad');
  }
}

async function grab(){
  const btn = $('btnGrab');
  btn.disabled = true;
  setStatus('正在读取当前页……', 'warn');
  try {
    const d = await getJSON('/api/menu/grab');
    if (!d.ok){ setStatus('✗ ' + (d.error || '抓取失败'), 'bad'); render(null); return; }
    const n = (d.dishes || []).length;
    if (n){
      setStatus('✓ 认出 ' + n + ' 项，合计 ' + money(d.total), 'ok');
    } else {
      setStatus('这一页没认出菜品（页面上有 ' + (d.price_nodes || 0) + ' 处价格）', 'warn');
    }
    render(d);
  } catch(e){
    setStatus('✗ 请求失败：' + e, 'bad');
  } finally {
    btn.disabled = false;
  }
}

async function closeBrowser(){
  setStatus('正在关闭浏览器……', 'warn');
  try {
    await getJSON('/api/menu/close');
    setStatus('浏览器已关闭。', '');
  } catch(e){
    setStatus('✗ 请求失败：' + e, 'bad');
  }
}

async function parsePaste(){
  const text = $('raw').value;
  if (!text.trim()){ setStatus('框是空的，先把菜单文本粘进来。', 'warn'); return; }
  try {
    const r = await fetch('/api/menu/parse', {
      method:'POST',
      headers:{'Content-Type':'text/plain; charset=utf-8'},
      body: text
    });
    const d = await r.json();
    if (d.ok === false){ setStatus('✗ ' + (d.error || '解析失败'), 'bad'); return; }
    setStatus('✓ 认出 ' + (d.dishes || []).length + ' 项', 'ok');
    render(d);
  } catch(e){
    setStatus('✗ 请求失败：' + e, 'bad');
  }
}
</script>
</body>
</html>
"""


def render_menu_page() -> str:
    return PAGE


# ──────────────────────────────────────────────────────────
# 示例菜单页：用来验证「一键抓」到底通不通
#
# 为什么需要它：真要验证抓取，得去平台页面、还得登录、还可能撞验证码，
# 任何一环出问题都说不清是工具的锅还是平台的锅。这一页把变量全去掉：
# 它就是一张本地页面，排版和真实菜单一样（菜名在左、价格在右、
# 划线原价、以及「起送/配送费」这种干扰项）。如果连这一页都抓不出来，
# 那是工具的问题，不用怀疑平台。
# ──────────────────────────────────────────────────────────

DEMO_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>示例小馆 - 自检用菜单页</title>
<style>
  body{margin:0;background:#f5f5f7;color:#1c1e21;
       font:16px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
  .wrap{max-width:520px;margin:0 auto;padding:16px}
  .shop{font-size:20px;font-weight:800;margin:0 0 4px}
  .meta{color:#8a8f98;font-size:13px;display:flex;gap:14px;margin-bottom:14px}
  .item{background:#fff;border-radius:12px;padding:14px;margin-bottom:10px;
        display:flex;align-items:center;gap:10px}
  .name{flex:1;font-weight:600}
  .was{color:#b0b4bb;font-size:12px;text-decoration:line-through}
  .price{font-weight:800;color:#e8452c;font-size:17px}
  .free{background:#e9f7ee;color:#1a9e46;border-radius:12px;padding:14px;
        margin-bottom:10px;font-weight:600}
  .promo{background:#fff6e5;color:#b26b00;border-radius:12px;padding:12px 14px;
         margin-bottom:12px;font-weight:600}
</style>
</head>
<body>
<div class="wrap">
  <h1 class="shop">示例小馆（自检用）</h1>
  <div class="meta">
    <span>评分 4.8分</span><span>月售9999+</span><span>起送</span><span>¥20</span>
  </div>

  <div class="promo">满30减5 满50减8 新客立减10元</div>

  <div class="item">
    <span class="name">麦辣鸡腿堡</span>
    <span class="was">¥19.0</span>
    <span class="price">¥12.9</span>
  </div>
  <div class="item">
    <span class="name">板烧鸡腿堡</span>
    <span class="price">¥13.9</span>
  </div>
  <div class="item">
    <span class="name">可乐（中）</span>
    <span class="was">¥6.0</span>
    <span class="price">¥0</span>
  </div>

  <div class="free">
    配送费 ¥3.5 · 打包费 ¥1
  </div>
  <div class="item">
    <span class="name">香辣鸡翅（2块）</span>
    <span class="price">¥14.0</span>
  </div>
</div>
</body>
</html>
"""


def render_demo_page() -> str:
    return DEMO_PAGE
