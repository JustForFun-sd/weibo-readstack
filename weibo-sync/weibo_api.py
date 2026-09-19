# -*- coding: utf-8 -*-
"""
m.weibo.cn 数据接口封装: 收藏夹 / 点赞列表。

★ 端点校准点 ★
如某来源抓取持续 404/解析为空, 用浏览器登录微博 -> F12 Network ->
打开对应页面(收藏夹/我点赞的), 找到同功能的 JSON 请求, 更新下面的
URL 模板即可, 其余代码不用动。/api/debug?url=... 可帮助比对。
"""
import json
import os
import re
import requests

M = "https://m.weibo.cn"
PC = "https://weibo.com"

# ★ 端点校准点 ★
# 点赞: 已验证可用的 PC 端接口 (返回 {"ok":1,"data":{"list":[...statuses]}})
LIKES_URL = PC + "/ajax/statuses/likelist?uid={uid}&page={page}&feature=0&rss=1"
# 收藏: 走 m 端 container/getIndex (该端点已验证真实存在);
# 收藏按文件夹存放, 需填一个 containerid (从浏览器 F12 抓"我的收藏"页 XHR 得到)。
# 若为空, 收藏来源会被跳过, 不影响点赞同步。
FAV_CONTAINER = os.environ.get("FAV_CONTAINER", "")
FAV_ITEMS = M + "/api/container/getIndex?containerid={container}&page={page}"
# PC 端收藏接口 (截图实证: /ajax/favorites/all_fav?page=1&with_total=1)
FAV_ALL = PC + "/ajax/favorites/all_fav?page={page}&with_total=1"
# PC 端收藏列表接口 (cookie 含 SUB_PRTS 时才有效; 返回 ok:1 + data.list[])
FAV_LIST = "https://weibo.com/ajax/favorites/statuslist?list_id=0&is_owner=1&type=1&page={page}&size=20&uid={uid}&folder_id="


def has_pc_cookie(cookie_str):
    return "SUB_PRTS=" in (cookie_str or "")


def current_uid(cookie_str):
    """取当前账号 uid: 依次尝试 m 端 / PC 首页 / 本地缓存。"""
    uid = get_uid(cookie_str)
    if uid:
        state_set_uid(uid)
        return uid
    # PC 首页 HTML 里带 uid
    try:
        r = requests.get(PC + "/", headers={"User-Agent": UA, "Cookie": cookie_str},
                         timeout=20)
        m = re.search(r'"uid":"?(\d{6,})"?', r.text)
        if m:
            state_set_uid(m.group(1))
            return m.group(1)
    except Exception:
        pass
    return state_get_uid()


def state_set_uid(uid):
    try:
        import state as _st
        s = _st.get_state(); s["uid"] = uid
        _st._save(_st.config.STATE_FILE, s)
    except Exception:
        pass


def state_get_uid():
    try:
        import state as _st
        return _st.get_state().get("uid", "")
    except Exception:
        return ""

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_UA_M = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
         "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Weibo/11.5.0")

_TAG_RE = re.compile(r"<[^>]+>")


def _headers(cookie_str, host=PC, ua=UA, xsrf=""):
    h = {
        "User-Agent": ua,
        "Referer": host + "/",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": cookie_str,
    }
    if xsrf:
        h["X-XSRF-TOKEN"] = xsrf
    return h


def _xsrf(cookie_str):
    m = re.search(r"XSRF-TOKEN=([^;]+)", cookie_str or "")
    return m.group(1) if m else ""


def get_uid(cookie_str):
    """从 m 端 config 拿当前登录用户 uid。"""
    try:
        r = requests.get(M + "/api/config",
                         headers=_headers(cookie_str, M, _UA_M), timeout=15)
        return str((r.json().get("data") or {}).get("uid", ""))
    except Exception:
        return ""


def validate(cookie_str):
    """校验 Cookie 是否为有效登录态(移动端或PC端任一即可), 返回 (ok, uid_or_msg)。"""
    # 1) 移动端
    try:
        r = requests.get(M + "/api/config",
                         headers=_headers(cookie_str, M, _UA_M), timeout=15)
        j = r.json()
        data = j.get("data") or {}
        if data.get("login") or data.get("uid"):
            uid = str(data.get("uid", ""))
            if uid:
                state_set_uid(uid)
            return True, uid or "ok"
    except Exception:
        pass
    # 2) PC 端 (用 all_fav 探测)
    try:
        r = requests.get(FAV_ALL.format(page=1),
                         headers=_headers(cookie_str, PC, UA, _xsrf(cookie_str)),
                         timeout=15)
        j = r.json()
        if j.get("ok") == 1:
            return True, current_uid(cookie_str) or "pc-ok"
        return False, "两端均未登录 (PC ok=%s)" % j.get("ok")
    except Exception as e:
        return False, "两端校验失败: %r" % e



def _clean(html_text):
    return _TAG_RE.sub("", html_text or "").replace("&nbsp;", " ").strip()


def normalize(st):
    """把一条微博 JSON 归一化; 保留原始 _st 供内容增强使用。"""
    if not isinstance(st, dict):
        return None
    mid = str(st.get("mid") or st.get("id") or st.get("idstr") or "")
    if not mid:
        return None
    text = _clean(st.get("text") or "")
    user = ((st.get("user") or {}).get("screen_name")) or ""
    url = ""
    pi = st.get("page_info") or {}
    pu = pi.get("page_url") or ""
    if pu.startswith("http"):
        url = pu
    if not url:
        uid_pc = (st.get("user") or {}).get("idstr") or ""
        bid = st.get("bid") or st.get("mblogid")
        if bid:
            url = "https://m.weibo.cn/status/%s" % bid
        elif uid_pc and mid:
            url = "https://weibo.com/%s/%s" % (uid_pc, mid)
        else:
            url = ("https://m.weibo.cn/detail/%s" % mid) if mid else ""
    return {"mid": mid, "url": url, "text": text[:4000],
            "title": ("%s: %s" % (user, text[:40])) if user else text[:60],
            "created": st.get("created_at", ""), "_st": st}


def _extract_pics(st):
    """从状态里抽取图片 URL 列表。"""
    urls = []
    for p in (st.get("pics") or []):
        if isinstance(p, dict):
            large = (p.get("large") or {}).get("url")
            urls.append(large or p.get("url") or p.get("thumbnail"))
    pi = st.get("page_info") or {}
    pic = (pi.get("page_pic") or {})
    if isinstance(pic, dict) and pic.get("url"):
        urls.append(pic["url"])
    return [u for u in urls if u and u.startswith("http")]


def fetch_longtext(cookie_str, mid):
    """长微博全文。"""
    try:
        r = requests.get(M + "/statuses/extend?id=" + str(mid),
                         headers=_headers(cookie_str, M, _UA_M), timeout=20)
        j = r.json()
        lt = (j.get("data") or {}).get("long_text_content") or j.get("data")
        if isinstance(lt, str):
            return _clean(lt)
    except Exception:
        pass
    return ""


def fetch_article(cookie_str, url):
    """头条文章正文: 带 cookie 抓 HTML, 抽取正文文本。"""
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Cookie": cookie_str,
                                       "Referer": PC + "/"}, timeout=25)
        html = r.text
        m = re.search(r'<div[^>]+class="[^"]*article"[^>]*>(.*?)</div>\s*</div>',
                      html, re.S)
        seg = m.group(1) if m else html
        seg = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", seg, flags=re.S)
        txt = _clean(seg)
        return txt[:8000]
    except Exception:
        return ""


def build_content(cookie_str, item):
    """组装推送正文 markdown: 作者/时间/正文/图/原文链接。"""
    st = item.get("_st") or {}
    text = item.get("text") or ""
    # 长文替换为全文
    if st.get("isLongText"):
        full = fetch_longtext(cookie_str, item["mid"])
        if full:
            text = full
    # 转发补充被转发内容
    rt = st.get("retweeted_status") or {}
    if rt:
        rt_txt = _clean(rt.get("text") or "")
        rt_user = (rt.get("user") or {}).get("screen_name", "")
        if rt_txt:
            text += "\n\n// @" + rt_user + ": " + rt_txt
    lines = [text.strip()]
    pics = _extract_pics(st)
    if pics:
        lines.append("\n".join("![img](%s)" % u for u in pics[:9]))
    # 头条文章正文
    pi = st.get("page_info") or {}
    pu = pi.get("page_url") or ""
    if pi.get("type") == "article" or "ttarticle" in pu or "/topics/" in pu:
        art = fetch_article(cookie_str, pu)
        if art:
            lines.append("---\n" + art)
    md = "\n\n".join(lines)
    if item.get("url"):
        md += "\n\n原文: " + item["url"]
    return md.strip()[:12000]


def _statuses_of(node):
    """从各种可能的响应结构里挖出微博条目列表 (含 card_group / mblog / 纯 status)。"""
    out = []
    if isinstance(node, dict):
        # container/getIndex: data.cards[].mblog 或 data.cards[].card_group[].mblog
        for card in node.get("cards") or []:
            if isinstance(card, dict):
                if card.get("mblog"):
                    out.append(card["mblog"])
                for g in card.get("card_group") or []:
                    if isinstance(g, dict) and g.get("mblog"):
                        out.append(g["mblog"])
        for key in ("statuslist", "statuses", "list", "status", "favorites"):
            for s in node.get(key) or []:
                if isinstance(s, dict):
                    out.append(s)
        if not out:  # 泛化递归: 深入任意 dict 型 value
            for v in node.values():
                if isinstance(v, dict):
                    got = _statuses_of(v)
                    if got:
                        out.extend(got)
                        break
    elif isinstance(node, list):
        for x in node:
            if isinstance(x, dict) and (x.get("mid") or x.get("id")):
                out.append(x)
            elif isinstance(x, dict):
                out.extend(_statuses_of(x))
    return [s for s in out if isinstance(s, dict) and (s.get("mid") or s.get("id") or s.get("idstr"))]


def fetch_favorites(cookie_str, pages=3, _uuid=None):
    """抓收藏。优先 PC all_fav 路由; 其次 m 端 container(需配 FAV_CONTAINER)。"""
    items = _fetch_favorites_pc(cookie_str, pages)
    if items:
        return items
    if not FAV_CONTAINER:
        return []
    return _fetch_favorites_m(cookie_str, pages)


def _fetch_favorites_pc(cookie_str, pages=3):
    """PC 收藏: 首选 /ajax/favorites/all_fav (全部收藏, 无需 uid)。"""
    h = _headers(cookie_str, PC, UA, _xsrf(cookie_str))
    items = []
    for p in range(1, pages + 1):
        r = requests.get(FAV_ALL.format(page=p), headers=h, timeout=20)
        try:
            j = r.json()
        except ValueError:
            break
        if j.get("ok") != 1:
            break
        batch = _statuses_of(j.get("data") or j)
        if not batch:
            break
        items.extend(batch)
    if items:
        return [n for n in (normalize(s) for s in items) if n]
    # 兜底: statuslist 路由(需要 uid)
    uid = current_uid(cookie_str)
    if not uid:
        return []
    items = []
    for p in range(1, pages + 1):
        r = requests.get(FAV_LIST.format(uid=uid, page=p), headers=h, timeout=20)
        try:
            j = r.json()
        except ValueError:
            break
        if j.get("ok") != 1:
            break
        batch = _statuses_of(j.get("data") or j)
        if not batch:
            break
        items.extend(batch)
    return [n for n in (normalize(s) for s in items) if n]


def _fetch_favorites_m(cookie_str, pages=3):
    h = _headers(cookie_str, M, _UA_M)
    items = []
    for p in range(1, pages + 1):
        r = requests.get(FAV_ITEMS.format(container=FAV_CONTAINER, page=p),
                         headers=h, timeout=20)
        j = r.json()
        if j.get("ok") != 1:
            break
        batch = _statuses_of(j.get("data") or j)
        if not batch:
            break
        items.extend(batch)
    return [n for n in (normalize(s) for s in items) if n]


def fetch_likes(cookie_str, pages=3):
    """抓我点赞的: PC 端 ajax/statuses/likelist (已验证可用)。"""
    uid = current_uid(cookie_str)
    if not uid:
        return []
    h = _headers(cookie_str, PC, UA, _xsrf(cookie_str))
    items = []
    for p in range(1, pages + 1):
        r = requests.get(LIKES_URL.format(uid=uid, page=p), headers=h, timeout=20)
        try:
            j = r.json()
        except ValueError:
            break
        batch = _statuses_of(j.get("data") or j)
        if not batch:
            break
        items.extend(batch)
    return [n for n in (normalize(s) for s in items) if n]


def debug_raw(cookie_str, url):
    """开发辅助: 原样取回某个接口 JSON, 用于端点校准。"""
    r = requests.get(url, headers=_headers(cookie_str, M, _UA_M), timeout=20)
    try:
        return json.loads(r.text)
    except Exception:
        return {"status_code": r.status_code, "text": r.text[:2000]}
