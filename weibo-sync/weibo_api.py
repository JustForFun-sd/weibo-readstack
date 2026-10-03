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

_ENTITIES = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
             "&quot;": '"', "&#39;": "'", "&#x27;": "'", "&middot;": "·",
             "&hellip;": "…", "&yen;": "¥", "&pound;": "£", "#39;": "'"}


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



def _unescape(s):
    for k, v in _ENTITIES.items():
        s = s.replace(k, v)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1)))
               if m.group(1).isdigit() and int(m.group(1)) < 0x110000 else "", s)
    return s


def _html_to_text(html):
    """微博 text/longText 的 HTML -> 排版友好纯文本: 保留换行, @/# 留文字,
    emoji 图转 [alt], 去掉 '全文' 锚文本(正文另有全文提取)。"""
    if not html:
        return ""
    s = html
    s = re.sub(r"(?is)<img[^>]*alt=([\"'])(.*?)\1[^>]*>", r"[\2]", s)
    s = re.sub(r"(?is)<img[^>]*>", "", s)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p>|</div>|</li>|</tr>", "\n", s)
    s = re.sub(r"(?is)<a[^>]*>\s*(全文|网页链接|O网页链接|查看图片|视频链接)\s*</a>", "", s)
    s = re.sub(r"(?is)<a[^>]*>|</a>", "", s)
    s = _TAG_RE.sub("", s)
    s = _unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _clean(html_text):
    return _html_to_text(html_text or "")


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


def _pic_url(p):
    """单张图片取最高清 URL, 并把 sinaimg 尺寸段统一升到 /large/。"""
    if not isinstance(p, str):
        if not isinstance(p, dict):
            return ""
        lg = p.get("large") or {}
        u = (lg.get("url") or lg.get("mobile") or p.get("url")
             or p.get("bmiddle") or p.get("thumbnail") or "")
    else:
        u = p
    u = _unescape(u)
    u = re.sub(r"/(thumbnail|bmiddle|orj360|orj480|small|wap180|square|cw180|fit|thumb960)/",
               "/large/", u)
    return u if u.startswith("http") else ""


def _extract_pics(st):
    """从状态里抽取图片 URL 列表(高清优先, 去重保序)。
    兼容三种结构: PC 端 pic_infos{pid:{largest/bmiddle..}} + pic_ids 排序、
    m 端 pics[]、page_info 封面。"""
    urls = []
    infos = st.get("pic_infos") or {}
    if isinstance(infos, dict) and infos:
        order = st.get("pic_ids") or list(infos.keys())
        for pid in order:
            v = infos.get(pid)
            if not isinstance(v, dict):
                continue
            u = ""
            for grade in ("largest", "large", "middleplus", "bmiddle", "thumbnail", "small"):
                g = v.get(grade) or {}
                u = g.get("url") or g.get("mobile") or ""
                if u:
                    break
            urls.append(_pic_url(u) if u else _pic_url(v))
    for p in (st.get("pics") or []):
        urls.append(_pic_url(p))
    pi = st.get("page_info") or {}
    pic = (pi.get("page_pic") or {})
    if isinstance(pic, dict) and pic.get("url") and (pi.get("type") or "") not in ("video",):
        urls.append(_pic_url(pic["url"]))
    out, seen = [], set()
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _status_url(st, fallback=""):
    """尽量构造该状态可播放/可读的网页链接(视频/图片点它最合适)。"""
    user = st.get("user") or {}
    uid = user.get("idstr") or ""
    mid = str(st.get("mid") or st.get("id") or st.get("idstr") or "")
    bid = st.get("bid") or st.get("mblogid") or ""
    if bid:
        return "https://m.weibo.cn/status/%s" % bid
    if uid and mid:
        return "https://weibo.com/%s/%s" % (uid, mid)
    if mid:
        return "https://m.weibo.cn/detail/%s" % mid
    return fallback or ""


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


def _long_content(st, cookie_str):
    """长文全文三级取法: 列表 JSON 自带 longText.content -> PC 详情接口 -> m 端 extend。"""
    lt = st.get("longText") or {}
    if isinstance(lt, dict) and lt.get("content"):
        return _html_to_text(lt["content"])
    if isinstance(lt, str) and lt.strip():
        return _html_to_text(lt)
    # PC 详情接口需要 SUB_PRTS; 残缺 cookie 直接跳过, 省时防限流
    if has_pc_cookie(cookie_str):
        ident = [str(st.get("mid") or st.get("id") or st.get("idstr") or "")]
        bid = st.get("bid") or st.get("mblogid")
        if bid:
            ident.append(str(bid))
        for key in ident:
            if not key:
                continue
            try:
                r = requests.get(PC + "/ajax/statuses/show?id=" + key,
                                 headers=_headers(cookie_str, PC, UA, _xsrf(cookie_str)),
                                 timeout=20)
                j = r.json()
                data = j.get("data") or j
                lt2 = data.get("longText") or {}
                if isinstance(lt2, dict) and lt2.get("content"):
                    return _html_to_text(lt2["content"])
                if data.get("text") and str(data.get("id") or data.get("mid") or "") == ident[0]:
                    return _html_to_text(data["text"])
            except Exception:
                pass
    return fetch_longtext(cookie_str, str(st.get("mid") or st.get("id") or st.get("idstr") or ""))


def _rich_lines(st, cookie_str):
    """把一条状态(主体或被转发源)展开成 markdown 块: 全文/图/视频/文章。"""
    out = []
    text = _html_to_text(st.get("text") or "")
    if st.get("longText") or st.get("isLongText"):
        full = _long_content(st, cookie_str)
        if full and len(full) >= len(text) - 3:   # 全文不早于截断版
            text = full
    pi = st.get("page_info") or {}
    ptype = pi.get("type") or ""
    mi = pi.get("media_info") or {}
    pu = pi.get("page_url") or ""
    is_video = (ptype == "video" or (mi and not ptype)
                or "object_type=video" in pu or "url_type=39" in pu)
    if is_video:
        title = _unescape(pi.get("page_title") or pi.get("title") or "").strip()
        vurl = _status_url(st)
        line = "▶ 视频" + (("《%s》" % title) if title else "")
        if vurl:
            line += " [播放](%s)" % vurl
        elif pu.startswith("http"):
            line += " [播放](%s)" % pu
        if text:
            out.append(text)
        out.append(line)
    elif ptype == "article" or "ttarticle" in pu:
        out.append(text or _unescape(pi.get("page_title") or pi.get("title") or ""))
        art = fetch_article(cookie_str, pi.get("page_url") or _status_url(st))
        if art:
            out.append("---\n" + art)
    else:
        if text:
            out.append(text)
        if pi.get("page_url", "").startswith("http") and ptype not in ("", "feed"):
            out.append("附页: %s (%s)" % (_unescape(pi.get("page_title")
                          or pi.get("title") or ""), pi["page_url"]))
    pics = _extract_pics(st)
    if pics:
        out.append("\n".join("![img%d](%s)" % (i + 1, u) for i, u in enumerate(pics[:18])))
    return [x for x in out if x and x.strip()]


def build_content(cookie_str, item):
    """组装推送正文 markdown: 主体全文/图/视频 + 被转发源完整内容 + 元信息。"""
    st = item.get("_st") or {}
    blocks = _rich_lines(st, cookie_str)
    rt = st.get("retweeted_status") or {}
    if isinstance(rt, dict) and rt:
        ru = (rt.get("user") or {}).get("screen_name", "")
        rblocks = _rich_lines(rt, cookie_str)
        rblocks.insert(0, ("—— 原博 @" + ru + ":") if ru else "—— 原博:")
        rurl = _status_url(rt)
        if rurl:
            rblocks.append("(原博: %s)" % rurl)
        blocks.append("\n\n".join(rblocks))
    meta = []
    created = item.get("created") or st.get("created_at") or ""
    if created:
        meta.append(str(created)[:16])
    if st.get("region_name"):
        meta.append(str(st["region_name"]))
    src = str(st.get("source") or "")
    if src and not src.startswith("http") and len(src) < 20:
        meta.append(src)
    if meta:
        blocks.append(" · ".join(meta))
    if item.get("url"):
        blocks.append("原文链接: " + item["url"])
    md = "\n\n".join(b for b in blocks if b and b.strip())
    # 标题升级: 作者 + 正文首行(更可读)
    user = (st.get("user") or {}).get("screen_name") or ""
    body_first = next((l for l in md.splitlines()
                       if l.strip() and not l.strip().startswith(("![", "▶", "—"))), "")
    if user and body_first:
        item["title"] = ("%s: %s" % (user, body_first.strip()))[:90]
    return md.strip()[:16000]


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
