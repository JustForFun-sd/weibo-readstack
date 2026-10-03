// ==UserScript==
// @name         微博 → NAS 稍后读自动搬运
// @namespace    readstack-weibo-sync
// @version      1.5
// @description  在浏览器登录态下抓取微博收藏/点赞(长文全文展开+全量翻页), 推送到自家 weibo-sync (免 Cookie 免 F12)
// @match        https://weibo.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_cookie
// @grant        GM_registerMenuCommand
// @grant        GM_setClipboard
// @grant        GM_notification
// @connect      192.168.30.165
// @run-at       document-idle
// @noframes
// ==/UserScript==

/* ===== 配置区: 只改这两行 ===== */
const NAS = "http://192.168.30.165:31900";   // weibo-sync 面板地址
const INTERVAL_MIN = 30;                      // 页面开着时每隔多少分钟自动同步一次
const FAV_PAGES = 40, LIKE_PAGES = 16;       // 每轮各抓几页 (全量: 服务端按 mid 去重, 重复页秒过)
/* ============================== */

const TAG = "[微博搬运]";

function gmFetch(url, opt = {}) {
  return new Promise((resolve, reject) => {
    GM_xmlhttpRequest({
      method: opt.method || "GET",
      url,
      headers: Object.assign({"content-type": "application/json"}, opt.headers || {}),
      data: opt.body,
      timeout: 30000,
      onload: r => {
        let j = null;
        try { j = JSON.parse(r.responseText); } catch (e) { j = r.responseText; }
        if (r.status >= 200 && r.status < 400) resolve(j);
        else reject(new Error("HTTP " + r.status + " " + url));
      },
      onerror: () => reject(new Error("网络失败 " + url)),
      ontimeout: () => reject(new Error("超时 " + url)),
    });
  });
}

// 从 weibo.com 页面内直接 fetch 微博接口 (浏览器同源, 自动带 Cookie)
const pageJson = url => fetch(url, {credentials: "include"}).then(r => r.json());

async function getUid() {
  try {
    if (window.PAGE_PROFILE && window.PAGE_PROFILE.uid) return String(window.PAGE_PROFILE.uid);
    if (window.$config && window.$config.user) return String(window.$config.user.uid);
  } catch (e) {}
  try {
    const html = await fetch("https://weibo.com/", {credentials: "include"}).then(r => r.text());
    const m = html.match(/"uid":"?(\d{6,})"?/);
    if (m) return m[1];
  } catch (e) {}
  return "";
}

// ---- 完整 Cookie 上报: SSO 重发探测为主, GM_cookie 仅诊断 ----
function reportCookie() {
  const diag = {v: (GM_info.script || {}).version || "1.5", t: Date.now()};
  const send = (str, via) => {
    diag.via = via;
    diag.final_len = (str || "").length;
    diag.final_hasP = /SUB_PRTS=/.test(str || "");
    gmFetch(NAS + "/api/diag", {method: "POST", body: JSON.stringify(diag)}).catch(() => {});
    if (str && /SUB=|SUB_PRTS=/.test(str)) {
      gmFetch(NAS + "/api/cookie", {method: "POST", body: JSON.stringify({cookie: str})})
        .then(r => console.log(TAG, "cookie 上报:", r && r.ok ? "成功" : (r && r.msg) || "失败"))
        .catch(() => {});
    }
  };
  try {   // GM_cookie 结果只记入诊断(稳定版过滤 HttpOnly, 不可依赖)
    GM_cookie.list({url: "https://weibo.com/"}, c => {
      diag.gm = "ok"; diag.gm_count = c ? c.length : -1;
      diag.gm_hasP = !!(c || []).some(x => x.name === "SUB_PRTS");
      diag.names = (c || []).map(x => x.name).slice(0, 20);
    }, e => { diag.gm = "err"; diag.gm_err = JSON.stringify(e).slice(0, 160); });
  } catch (e) { diag.gm = "throw"; diag.gm_throw = String(e).slice(0, 120); }
  ssoProbe(send, diag);
}

// ---- SSO 重发探测: login.php 对已登录会话会重新下发全套 Set-Cookie(含 SUB_PRTS) ----
function ssoProbe(send, diag) {
  GM_xmlhttpRequest({
    method: "GET",
    url: "https://login.sina.com.cn/sso/login.php?entry=weibo&retcode=6102",
    headers: {"User-Agent": navigator.userAgent},
    timeout: 15000,
    onload: r => {
      diag.sso_status = r.status;
      const rh = (r.responseHeaders || "").split("\n").filter(x => /set-cookie/i.test(x));
      diag.sso_headers = rh.length;
      diag.sso_setcookies = rh.map(x => x.trim().slice(0, 60)).slice(0, 12);
      const jar = {};
      rh.forEach(line => {
        const m = line.match(/set-cookie:\s*([^=;]+)=([^;]*)/i);
        if (m) jar[m[1]] = m[2];
      });
      diag.jar_names = Object.keys(jar);
      if (jar.SUB || jar.SUB_PRTS) send(Object.keys(jar).map(k => k + "=" + jar[k]).join("; "), "sso");
      else send(document.cookie, "doc");
    },
    onerror: () => { diag.sso = "neterr"; send(document.cookie, "doc"); },
    ontimeout: () => { diag.sso = "timeout"; send(document.cookie, "doc"); },
  });
}

try {
  GM_registerMenuCommand("🔄 刷新并上报 Cookie (SSO)", () =>
    ssoProbe((s, v) => alert("via " + v + " hasP=" + /SUB_PRTS=/.test(s)), {v: "menu"}));
} catch (e) {}

// ---- 浏览器内长文展开: isLongText 但无 longText.content 的, 同源请求详情补齐 ----
async function expandLongTexts(statuses, budget) {
  let used = 0;
  const jobs = [];
  const walk = s => {
    if (!s || typeof s !== "object") return;
    const lt = s.longText;
    const need = s.isLongText && !(lt && (typeof lt === "string" ? lt : lt.content));
    if (need && used < budget) {
      used++;
      const id = s.mid || s.id || s.idstr || s.bid || s.mblogid;
      if (id) jobs.push(fetch("https://weibo.com/ajax/statuses/show?id=" + id,
        {credentials: "include"}).then(r => r.json()).then(j => {
          const d = (j && j.data) || j || {};
          if (d.longText) s.longText = d.longText;
          if (d.pics) s.pics = s.pics || d.pics;
          if (d.pic_infos) s.pic_infos = s.pic_infos || d.pic_infos;
          if (d.page_info) s.page_info = s.page_info || d.page_info;
        }).catch(() => {}));
    }
    if (s.retweeted_status) walk(s.retweeted_status);
  };
  statuses.forEach(walk);
  await Promise.all(jobs);
}

function statusesOf(node, out) {
  out = out || [];
  if (Array.isArray(node)) { node.forEach(x => statusesOf(x, out)); return out; }
  if (!node || typeof node !== "object") return out;
  if (node.mid || node.id || node.idstr) { out.push(node); return out; }
  (node.cards || []).forEach(c => {
    if (c && c.mblog) out.push(c.mblog);
    (c && c.card_group || []).forEach(g => g && g.mblog && out.push(g.mblog));
  });
  ["statuslist", "statuses", "list", "status"].forEach(k => {
    if (Array.isArray(node[k])) node[k].forEach(s => s && statusesOf(s, out));
  });
  if (!out.length || (!node.cards && !node.list)) Object.values(node).forEach(v => {
    if (v && typeof v === "object") statusesOf(v, out);
  });
  return out.filter(s => s && (s.mid || s.id || s.idstr));
}

async function pushPages(kind, urlOf, pages) {
  let total = 0;
  for (let p = 1; p <= pages; p++) {
    let j;
    try { j = await pageJson(urlOf(p)); } catch (e) { console.warn(TAG, e); break; }
    if (!j || j.ok !== 1) break;
    try { await expandLongTexts(statusesOf(j.data || j), 25); }
    catch (e) { console.warn(TAG, "长文展开跳过:", e); }
    let res;
    try {
      res = await gmFetch(NAS + "/api/ingest",
        {method: "POST", body: JSON.stringify({kind, data: j})});
    } catch (e) { console.warn(TAG, "NAS 不可达:", e); break; }
    total += (res && res.pushed) || 0;
    if (!res || !res.more) break;
  }
  return total;
}

async function syncAll(manual) {
  reportCookie();
  const fav = await pushPages("fav", i =>
    "https://weibo.com/ajax/favorites/all_fav?page=" + i + "&with_total=1", FAV_PAGES);
  const uid = await getUid();
  let like = 0;
  if (uid) {
    like = await pushPages("like", i =>
      "https://weibo.com/ajax/statuses/likelist?uid=" + uid + "&page=" + i + "&feature=0&rss=1", LIKE_PAGES);
  }
  const msg = "收藏+" + fav + "，点赞+" + like + (uid ? "" : "(未取得uid跳过点赞)");
  console.log(TAG, msg);
  if (manual) alert(TAG + " 同步完成: " + msg);
}

window.addEventListener("load", () => setTimeout(() => syncAll(false), 5000));
setInterval(() => syncAll(false), INTERVAL_MIN * 60000);

// 菜单手动触发
const btn = document.createElement("div");
btn.textContent = "☁ 同步到NAS";
btn.style.cssText = "position:fixed;right:16px;bottom:96px;z-index:99999;background:#07c;color:#fff;padding:8px 12px;border-radius:20px;cursor:pointer;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,.3)";
btn.onclick = () => syncAll(true);
document.body.appendChild(btn);
