// ==UserScript==
// @name         微博 → NAS 稍后读自动搬运
// @namespace    readstack-weibo-sync
// @version      1.0
// @description  在浏览器登录态下直接抓取微博收藏/点赞, 推送到自家 weibo-sync (免 Cookie 免 F12)
// @match        https://weibo.com/*
// @grant        GM_xmlhttpRequest
// @connect      192.168.30.165
// @run-at       document-idle
// @noframes
// ==/UserScript==

/* ===== 配置区: 只改这两行 ===== */
const NAS = "http://192.168.30.165:31900";   // weibo-sync 面板地址
const INTERVAL_MIN = 30;                      // 页面开着时每隔多少分钟自动同步一次
const FAV_PAGES = 3, LIKE_PAGES = 2;          // 每轮各抓几页 (3页≈60条收藏, 2页≈40条点赞)
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
  // 从当前页面全局变量或首页 HTML 里取自己 uid
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

async function pushPages(kind, urlOf, pages) {
  let total = 0;
  for (let p = 1; p <= pages; p++) {
    let j;
    try { j = await pageJson(urlOf(p)); } catch (e) { console.warn(TAG, e); break; }
    if (!j || j.ok !== 1) break;
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
  // 顺带上报 Cookie, 让服务端后台轮询也保持有效 (https 页面里 document.cookie 含 SUB 即可用)
  if (/SUB=/.test(document.cookie)) {
    gmFetch(NAS + "/api/cookie", {method: "POST",
      body: JSON.stringify({cookie: document.cookie})}).catch(() => {});
  }
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
