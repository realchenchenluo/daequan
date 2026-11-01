// ==UserScript==
// @name         菜单提取（大全网）
// @namespace    https://github.com/realchenchenluo/daequan
// @version      1.0.0
// @description  在你自己的浏览器里，把当前外卖店铺页的菜单和价格整理成结构化文本，复制到剪贴板。只读、不联网、不下单。
// @author       大全网
// @match        https://h5.waimai.meituan.com/*
// @match        https://i.waimai.meituan.com/*
// @match        https://h5.ele.me/*
// @match        https://www.ele.me/*
// @run-at       document-idle
// @grant        GM_setClipboard
// @grant        none
// ==/UserScript==

/*
 * 为什么用这种方式，而不是我去登录、自动抓
 * ────────────────────────────────────────
 * 这个脚本运行在**你自己平时用的浏览器**里，用的是你**已经登录**的会话。
 *
 *   1. 工具的代码永远拿不到你的 cookie —— 它只拿到一段文字。
 *   2. 不额外发任何网络请求：不调接口、不翻页、不轮询，
 *      访问量和你自己手动逛完全一样。
 *   3. 只有你点按钮的时候它才跑一次，不会在后台偷偷跑。
 *   4. 读到的东西原样显示在一个预览框里，你能看见它拿到了什么，
 *      确认没问题再复制。它不是黑盒。
 *
 * 仍然要如实说明：自动读取页面内容这件事，在多数平台的用户协议里
 * 是不被鼓励的。这个脚本把能缩的地方都缩了（不批量、不请求、不交凭证），
 * 但"自动化"这个性质没有变。你自己决定用不用。
 */

(function () {
  "use strict";

  // ── 版本标记：方便你在预览框里确认装的是新版 ──────────────
  const VERSION = "1.0.0";

  const PRICE_RE = /^[¥￥]?\s*(\d{1,5}(?:[.·]\d{1,2})?)\s*[起元]?$/;
  const SNIFF_RE = /[¥￥]\s*\d{1,5}(?:[.·]\d{1,2})?|\d{1,5}(?:[.·]\d{1,2})?\s*元/;

  // 这些文字是界面标签，不是菜名
  const NOISE = [
    "起送", "配送", "打包", "配送费", "月售", "已售", "评分", "人数", "评价",
    "优惠", "特价", "折扣", "领券", "满减", "会员", "红包", "加入购物车",
    "选规格", "去结算", "购物车", "差", "起", "元", "折", "剩余", "限购",
    "招牌", "热销", "新品", "推荐", "首页", "订单", "我的", "搜索", "全部",
    "商家", "公告", "详情", "规则", "说明",
  ];

  // ── 小工具 ──────────────────────────────────────────
  function norm(s) {
    return (s || "").replace(/\s+/g, " ").trim();
  }

  function visible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const st = getComputedStyle(el);
    return st.visibility !== "hidden" && st.display !== "none" && st.opacity !== "0";
  }

  function parseAmount(raw) {
    const s = norm(raw).replace(/[·]/g, ".");
    const m = s.match(/(\d{1,5}(?:\.\d{1,2})?)/);
    return m ? parseFloat(m[1]) : null;
  }

  function isNoise(text) {
    const t = norm(text);
    if (!t) return true;
    if (t.length > 60) return true;
    for (const w of NOISE) {
      if (t === w) return true;
    }
    // 纯数字/纯标点/纯价格
    if (PRICE_RE.test(t)) return true;
    if (/^[\d\s¥￥.,·\-+*/%]+$/.test(t)) return true;
    return false;
  }

  // ── 找「价格节点」──────────────────────────────────
  // 策略：找出文本本身就是价格的**叶子节点**，再往上找它的容器。
  // 这样不依赖 class 名，平台改版只要还是"名字 + 价格"的视觉结构就还能用。
  function findPriceNodes() {
    const out = [];
    const all = document.body.querySelectorAll("*");
    for (const el of all) {
      if (el.children.length > 0) continue; // 只看叶子
      const t = norm(el.textContent);
      if (!t || t.length > 12) continue;
      if (!PRICE_RE.test(t)) continue;
      if (!visible(el)) continue;
      out.push(el);
    }
    return out;
  }

  // 从价格节点往上找容器，再在容器里找最像菜名的文字
  function nameNear(priceEl) {
    let node = priceEl.parentElement;
    for (let depth = 0; depth < 5 && node; depth++) {
      const cands = [];
      const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
      let n;
      while ((n = walker.nextNode())) {
        const t = norm(n.nodeValue);
        if (!t || isNoise(t)) continue;
        if (SNIFF_RE.test(t) && t.length <= 12) continue; // 别的价格
        const parent = n.parentElement;
        if (!parent || !visible(parent)) continue;
        cands.push({ text: t, len: t.length });
      }
      if (cands.length) {
        // 菜名通常是最长的那段非价格文字
        cands.sort((a, b) => b.len - a.len);
        const best = cands[0].text;
        // 太长的不像菜名（整段介绍）
        if (best.length <= 40) return best;
      }
      node = node.parentElement;
    }
    return "";
  }

  // 同一容器里的划线价当作原价
  function originalNear(priceEl) {
    let node = priceEl.parentElement;
    for (let depth = 0; depth < 3 && node; depth++) {
      for (const el of node.querySelectorAll("*")) {
        if (el === priceEl || el.contains(priceEl)) continue;
        const t = norm(el.textContent);
        if (!t || t.length > 12) continue;
        const st = getComputedStyle(el);
        const lined =
          st.textDecorationLine.includes("line-through") ||
          (el.tagName === "DEL") ||
          (el.tagName === "S");
        if (!lined) continue;
        const v = parseAmount(t);
        if (v !== null) return v;
      }
      node = node.parentElement;
    }
    return null;
  }

  function guessStoreName() {
    // 优先用文档标题（通常是「店名 - 美团外卖」）
    const t = norm(document.title);
    if (t) {
      const head = t.split(/[-_|｜]/)[0].trim();
      if (head && head.length <= 30) return head;
    }
    // 退而求其次：页面顶部第一段够长的中文
    const all = document.body.querySelectorAll("h1,h2,div,span");
    for (const el of all) {
      if (el.children.length) continue;
      const s = norm(el.textContent);
      if (s.length >= 4 && s.length <= 30 && /[\u4e00-\u9fff]/.test(s) && !isNoise(s)) {
        return s;
      }
    }
    return "";
  }

  function guessSource() {
    const h = location.hostname;
    if (h.includes("meituan")) return "美团";
    if (h.includes("ele.me")) return "淘宝闪购/饿了么";
    return h;
  }

  // ── 主流程 ──────────────────────────────────────────
  function extract() {
    const nodes = findPriceNodes();
    const seen = new Set();
    const rows = [];

    for (const el of nodes) {
      const price = parseAmount(el.textContent);
      if (price === null || price <= 0 || price > 99999) continue;

      const name = nameNear(el);
      if (!name) continue;

      const key = name + "|" + price;
      if (seen.has(key)) continue;
      seen.add(key);

      rows.push({ name, price, original: originalNear(el) });
    }

    return {
      store: guessStoreName(),
      source: guessSource(),
      rows,
    };
  }

  function toText(result) {
    const lines = [];
    if (result.store) lines.push("#店 " + result.store);
    lines.push("#来源 " + result.source);
    lines.push("#数量 " + result.rows.length);
    for (const r of result.rows) {
      const parts = [r.name, String(r.price)];
      if (r.original !== null && r.original > r.price) parts.push(String(r.original));
      lines.push(parts.join("\t"));
    }
    return lines.join("\n");
  }

  function copy(text) {
    if (typeof GM_setClipboard === "function") {
      GM_setClipboard(text, "text");
      return true;
    }
    // 退路：老办法，靠一个临时 textarea
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (e) {
      return false;
    }
  }

  // ── 界面 ────────────────────────────────────────────
  let panel = null;

  function closePanel() {
    if (panel && panel.parentNode) panel.parentNode.removeChild(panel);
    panel = null;
  }

  function showPanel(result, text) {
    closePanel();
    panel = document.createElement("div");
    panel.style.cssText = [
      "position:fixed", "right:16px", "bottom:16px", "width:380px",
      "max-height:70vh", "overflow:auto", "z-index:2147483647",
      "background:#1f2430", "color:#e8ecf1", "border-radius:10px",
      "box-shadow:0 8px 28px rgba(0,0,0,.45)", "font:13px/1.55 -apple-system,'Microsoft YaHei',sans-serif",
      "padding:12px 14px",
    ].join(";");

    const total = result.rows.reduce((s, r) => s + r.price, 0);
    const head = document.createElement("div");
    head.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:8px";
    head.innerHTML =
      '<b style="font-size:14px">菜单提取 v' + VERSION + "</b>";
    const x = document.createElement("span");
    x.textContent = "关闭 ✕";
    x.style.cssText = "cursor:pointer;color:#9aa7b8";
    x.onclick = closePanel;
    head.appendChild(x);
    panel.appendChild(head);

    const info = document.createElement("div");
    info.style.cssText = "color:#9aa7b8;margin-bottom:8px";
    info.textContent =
      (result.store || "（没认出店名）") +
      " · " + result.source +
      " · 认出 " + result.rows.length + " 项 · 合计 ¥" + total.toFixed(2);
    panel.appendChild(info);

    const list = document.createElement("div");
    list.style.cssText = "max-height:160px;overflow:auto;border:1px solid #333c4d;border-radius:6px;padding:6px;background:#171b24";
    for (const r of result.rows.slice(0, 200)) {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;justify-content:space-between;gap:8px;padding:2px 0";
      const n = document.createElement("span");
      n.textContent = r.name;
      n.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
      const p = document.createElement("span");
      p.textContent = r.original !== null && r.original > r.price
        ? "¥" + r.price.toFixed(2) + " (原¥" + r.original.toFixed(2) + ")"
        : "¥" + r.price.toFixed(2);
      p.style.cssText = "flex:none;color:#7fd18b";
      row.appendChild(n);
      row.appendChild(p);
      list.appendChild(row);
    }
    if (!result.rows.length) {
      list.textContent = "没认出任何菜品。可能是页面还没渲染完，或者这一页不是店铺菜单页。";
      list.style.color = "#e0a45e";
    }
    panel.appendChild(list);

    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = [
      "width:100%", "height:90px", "margin-top:8px", "box-sizing:border-box",
      "background:#171b24", "color:#c8d2df", "border:1px solid #333c4d",
      "border-radius:6px", "padding:6px", "font:11px/1.4 Consolas,monospace",
      "resize:vertical",
    ].join(";");
    panel.appendChild(ta);

    const btn = document.createElement("button");
    btn.textContent = "复制这段文本";
    btn.style.cssText = [
      "margin-top:8px", "width:100%", "padding:8px", "cursor:pointer",
      "background:#3b82f6", "color:#fff", "border:0", "border-radius:6px",
      "font-size:13px",
    ].join(";");
    btn.onclick = function () {
      const ok = copy(ta.value);
      btn.textContent = ok ? "已复制 ✓" : "复制失败，请手动全选复制";
      setTimeout(function () {
        btn.textContent = "复制这段文本";
      }, 1600);
    };
    panel.appendChild(btn);

    const tip = document.createElement("div");
    tip.style.cssText = "margin-top:8px;color:#7b8798;font-size:11px;line-height:1.5";
    tip.textContent =
      "复制后到工具里运行：python run.py 粘贴";
    panel.appendChild(tip);

    document.body.appendChild(panel);
  }

  // 单页应用切路由时按钮会被冲掉，兜一下
  function ensureButton() {
    if (!document.body) return;
    if (document.getElementById("__dq_menu_btn__")) return;
    const b = document.createElement("div");
    b.id = "__dq_menu_btn__";
    b.textContent = "📋 提取菜单";
    b.style.cssText = [
      "position:fixed", "right:16px", "top:96px", "z-index:2147483647",
      "background:#3b82f6", "color:#fff", "padding:8px 12px", "border-radius:8px",
      "font:13px/1 -apple-system,'Microsoft YaHei',sans-serif", "cursor:pointer",
      "box-shadow:0 4px 14px rgba(0,0,0,.3)", "user-select:none",
    ].join(";");
    b.onclick = function () {
      b.textContent = "提取中…";
      setTimeout(function () {
        let result;
        try {
          result = extract();
        } catch (e) {
          result = { store: "", source: guessSource(), rows: [] };
          console.error("[菜单提取] 出错：", e);
        }
        showPanel(result, toText(result));
        b.textContent = "📋 提取菜单";
      }, 30);
    };
    document.body.appendChild(b);
  }

  ensureButton();
  const obs = new MutationObserver(function () {
    if (document.getElementById("__dq_menu_btn__")) return;
    ensureButton();
  });
  obs.observe(document.documentElement, { childList: true, subtree: true });
})();
