"""
「最高折扣」页面。

这一页回答三个问题，顺序也是用户真正关心的顺序：
  1. 这单最多能省多少钱、到手多少？
  2. 这些券从哪领？（给链接、给口令、给去哪点的说明）
  3. 具体怎么操作？

数据来源分开标清楚，不含糊：
  · 通用券 —— 平台发的，自动抓（就是主页那份券数据）
  · 店家券 —— 只印在那家店的页面上，靠「菜单抓取」读出来或者你粘进来
"""

from __future__ import annotations

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0f1115">
<title>最高折扣 · 大全网</title>
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
  .card h2{font-size:15px;margin:0 0 12px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .field{display:flex;flex-direction:column;gap:4px}
  .field label{font-size:12.5px;color:var(--dim)}
  .field.full{grid-column:1 / -1}
  input,select,textarea{width:100%;background:var(--bg);border:1px solid var(--line);
        border-radius:12px;color:var(--text);padding:11px;font-size:15px;font-family:inherit}
  textarea{min-height:70px;font-size:12.5px}
  button{border:none;border-radius:12px;padding:13px 14px;font-size:15px;font-weight:700;
         cursor:pointer;min-height:48px;background:var(--line);color:var(--text)}
  button:active{transform:scale(.98)}
  button:disabled{opacity:.45}
  button.primary{background:var(--blue);color:#fff;width:100%}
  button.small{font-size:12.5px;padding:6px 10px;min-height:0;border-radius:8px;
               background:transparent;border:1px solid var(--line);color:var(--blue)}
  .big{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
  .big .n{font-size:32px;font-weight:800;color:var(--green)}
  .big .t{color:var(--dim);font-size:13px}
  .kv{display:flex;justify-content:space-between;padding:6px 0;font-size:14px}
  .kv .d{color:var(--dim)}
  .pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11.5px;
        font-weight:600;margin-left:6px;vertical-align:middle}
  .pill.shop{background:rgba(255,214,10,.16);color:var(--accent)}
  .pill.uni{background:rgba(77,163,255,.16);color:var(--blue)}
  .pill.cap{background:rgba(255,107,107,.16);color:var(--red)}
  .item{padding:10px 0;border-bottom:1px solid var(--line)}
  .item:last-child{border-bottom:none}
  .item .t{font-size:14px;font-weight:600}
  .item .m{color:var(--dim);font-size:12.5px;margin-top:3px;word-break:break-all}
  ol.steps{margin:0;padding-left:20px;font-size:14px;line-height:1.85}
  ol.steps li{margin-bottom:6px}
  .warnbox{color:var(--dim);font-size:12.5px;line-height:1.7;margin-top:8px}
  .warn{color:var(--accent);font-size:12.5px;line-height:1.7;margin-top:8px}
  .err{color:var(--red);font-size:14px}
  .empty{color:var(--dim);font-size:13.5px}
  .link{color:var(--blue);text-decoration:none;font-size:13px}
</style>
</head>
<body>
<div class="wrap">
  <h1>最高折扣</h1>
  <div class="sub">给一单，算出最多省多少、券从哪领、按什么顺序点。
    <a href="/menu">← 先去抓菜单</a></div>

  <div class="card">
    <h2>这一单</h2>
    <div class="grid">
      <div class="field full">
        <label>平台</label>
        <select id="platform">
          <option>美团</option>
          <option>淘宝闪购</option>
          <option>京东外卖</option>
        </select>
      </div>
      <div class="field">
        <label>菜品合计（优惠前）</label>
        <input id="items" type="number" step="0.01" min="0" placeholder="40.80">
      </div>
      <div class="field">
        <label>配送费</label>
        <input id="delivery" type="number" step="0.01" min="0" placeholder="3.5">
      </div>
      <div class="field">
        <label>打包费</label>
        <input id="packing" type="number" step="0.01" min="0" placeholder="1">
      </div>
      <div class="field">
        <label>有会员（免配送/会员券）</label>
        <select id="member"><option value="0">没有</option><option value="1">有</option></select>
      </div>
      <div class="field full">
        <label>店铺优惠（可留空，会自动用上次抓取的结果）</label>
        <textarea id="promos" placeholder="例如：满30减5 满50减8 新客立减10元"></textarea>
      </div>
    </div>
    <div style="margin-top:12px">
      <button class="primary" id="go" onclick="calc()">算最高折扣</button>
    </div>
    <div class="warnbox" id="hint"></div>
  </div>

  <div id="out"></div>
</div>

<script>
const $ = (id) => document.getElementById(id);

function esc(s){
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function money(v){ return '¥' + Number(v || 0).toFixed(2); }

// 从 /menu 跳过来时会带参数，先填上
(function prefill(){
  const q = new URLSearchParams(location.search);
  for (const k of ['platform','items','delivery','packing','member','promos']){
    const v = q.get(k);
    if (v !== null && v !== '' && $(k)) $(k).value = v;
  }
})();

async function calc(){
  const items = parseFloat($('items').value || '0');
  if (!(items > 0)){
    $('out').innerHTML = '<div class="card"><div class="err">先填菜品合计（优惠前的金额）。</div></div>';
    return;
  }
  const btn = $('go');
  btn.disabled = true;
  $('hint').textContent = '正在算……（第一次会先抓一次券，可能要几秒）';
  try {
    const q = new URLSearchParams({
      platform: $('platform').value,
      items: String(items),
      delivery: $('delivery').value || '0',
      packing: $('packing').value || '0',
      member: $('member').value,
    });
    const promos = $('promos').value.trim();
    if (promos) q.set('promos', promos);

    const r = await fetch('/api/discount/plan?' + q.toString(), {cache:'no-store'});
    const d = await r.json();
    $('hint').textContent = '';
    render(d);
  } catch(e){
    $('hint').textContent = '';
    $('out').innerHTML = '<div class="card"><div class="err">请求失败：' + esc(e) + '</div></div>';
  } finally {
    btn.disabled = false;
  }
}

function couponRow(c, kind){
  const pill = kind === 'cap'
    ? '<span class="pill cap">面额是上限，没算进去</span>'
    : '<span class="pill uni">平台通用券</span>';
  let actions = '';
  if (c.code){
    actions += '<button class="small" onclick="copyCode(this,\\'' + esc(c.code).replace(/'/g,'') + '\\')">复制口令</button> ';
  }
  if (c.url){
    actions += '<a class="small link" style="display:inline-block;padding:6px 10px;border:1px solid var(--line);border-radius:8px" href="' + esc(c.url) + '" target="_blank" rel="noopener noreferrer">去领取</a> ';
  }
  return '<div class="item">'
    + '<div class="t">' + esc(c.title || '（无标题）') + pill + '</div>'
    + '<div class="m">' + esc(c.discount_text || '') 
    + (c.guideline ? ' · ' + esc(c.guideline) : '')
    + (c.code ? '<br>口令：<b>' + esc(c.code) + '</b>' : '')
    + '</div>'
    + (actions ? '<div style="margin-top:8px">' + actions + '</div>' : '')
    + '</div>';
}

function copyCode(el, code){
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(code).then(function(){
      el.textContent = '已复制';
      setTimeout(function(){ el.textContent = '复制口令'; }, 1500);
    });
  } else {
    el.textContent = '请手动复制：' + code;
  }
}

function render(d){
  const out = $('out');
  if (!d || d.ok === false){
    out.innerHTML = '<div class="card"><div class="err">'
      + esc((d && d.error) || '没拿到结果') + '</div></div>';
    return;
  }

  let html = '';

  // 1) 结果数字
  html += '<div class="card">';
  html += '<h2>' + esc(d.platform) + ' · 这单最多能省</h2>';
  html += '<div class="big"><span class="n">' + money(d.max_discount) + '</span>'
       +  '<span class="t">到手约 ' + money(d.final_price) + '（含配送和打包）</span></div>';
  html += '<div style="margin-top:12px">';
  html += '<div class="kv"><span class="d">菜品优惠后</span><span>' + money(d.food_after) + '</span></div>';
  html += '<div class="kv"><span class="d">配送费</span><span>' + money(d.delivery) + '</span></div>';
  html += '<div class="kv"><span class="d">打包费</span><span>' + money(d.packing) + '</span></div>';
  html += '</div>';
  html += '</div>';

  // 2) 券从哪来
  html += '<div class="card"><h2>券从哪来</h2>';

  const sp = d.store_promos || [];
  if (sp.length){
    html += '<div class="warnbox" style="margin-top:0;margin-bottom:6px">'
         + '店铺优惠（只在这家店能用，抓页面时读到的）：</div>';
    sp.forEach(function(p){
      html += '<div class="item"><div class="t">' + esc(p.describe)
           +  '<span class="pill shop">店家券</span></div>'
           +  '<div class="m">页面原文：' + esc(p.text) + '</div></div>';
    });
  } else {
    html += '<div class="empty" style="margin-bottom:10px">'
         + '没有读到店铺优惠。有些店的满减要进店才看得到，'
         + '去 <a class="link" href="/menu">菜单抓取</a> 抓一次，或者直接把页面上的文字粘到上面那一栏。</div>';
  }

  const uu = d.usable_universal || [];
  if (uu.length){
    html += '<div class="warnbox" style="margin-top:12px;margin-bottom:6px">'
         + '平台通用券（已算进上面的金额）：</div>';
    uu.forEach(function(c){ html += couponRow(c, 'uni'); });
  } else {
    html += '<div class="warnbox">没找到面额明确的平台券。券源给的大多是「最高抢 X 元」，'
         + '那是上限不是保底，算进去会让你以为能省很多，所以我不算。</div>';
  }

  const cap = d.display_only || [];
  if (cap.length){
    html += '<div class="warnbox" style="margin-top:12px;margin-bottom:6px">'
         + '能领但面额不确定（没算进金额）：</div>';
    cap.forEach(function(c){ html += couponRow(c, 'cap'); });
  }
  html += '</div>';

  // 3) 凑单
  const tu = d.top_up || [];
  if (tu.length){
    html += '<div class="card"><h2>凑单建议</h2>';
    tu.forEach(function(t){
      html += '<div class="item"><div class="t">再买 ' + money(t.gap) + ' 就能用「'
           +  esc(t.name) + '」</div>'
           +  '<div class="m">这一档减 ' + money(t.value)
           +  '，比现在多省 ' + money(t.gain) + '</div></div>';
    });
    html += '</div>';
  }

  // 4) 操作步骤
  html += '<div class="card"><h2>怎么操作</h2><ol class="steps">';
  (d.steps || []).forEach(function(s){ html += '<li>' + esc(s) + '</li>'; });
  html += '</ol>';
  (d.warnings || []).forEach(function(w){
    html += '<div class="warn">⚠️ ' + esc(w) + '</div>';
  });
  html += '</div>';

  out.innerHTML = html;
}
</script>
</body>
</html>
"""


def render_discount_page() -> str:
    return PAGE
