# -*- coding: utf-8 -*-
"""
微博扫码登录 (2024/2025 现行协议)。流程:
  1) GET  login.sina.com.cn/sso/qrcode/image?entry=weibo&size=180  -> qrid + image
  2) GET  login.sina.com.cn/sso/qrcode/check?entry=weibo&qrid=..    -> 轮询, retcode==20000000 时给出 data.alt
  3) GET  login.sina.com.cn/sso/login.php?entry=weibo&alt=<alt>      -> 302, Set-Cookie 里拿到 SUB 等
另: 部分环境先要 visitor 拿 aid, 这里做容错, 失败再补一次带 aid 的请求。
"""
import re
import time
import requests
from urllib.parse import quote

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

IMG_URL   = "https://login.sina.com.cn/sso/qrcode/image"
CHECK_URL = "https://login.sina.com.cn/sso/qrcode/check"
LOGIN_URL = "https://login.sina.com.cn/sso/login.php"
VISITOR   = "https://passport.weibo.com/visitor/genvisitor"


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://weibo.com/"})
    return s


def _genvisitor(s):
    """尽力获取 visitor 凭证(部分接口需要)。失败也不影响主流程。"""
    try:
        r = s.get(VISITOR, params={"cb": "visitor_callback", "w": 3}, timeout=15)
        m = re.search(r'"tid":"(.*?)"', r.text)
        return m.group(1) if m else ""
    except Exception:
        return ""


def start():
    """生成二维码。返回 (session, qrid, 图片URL)。"""
    s = _session()
    _genvisitor(s)  # 预热 visitor cookie, 容错
    r = s.get(IMG_URL, params={"entry": "weibo", "size": "180"}, timeout=15)
    r.raise_for_status()
    qrid_m = re.search(r'"qrid":"(.*?)"', r.text)
    img_m = re.search(r'"image":"(.*?)"', r.text)
    if not qrid_m:
        raise RuntimeError("二维码接口未返回 qrid (可能改版): %s" % r.text[:200])
    img = img_m.group(1).replace("\\/", "/") if img_m else ""
    return s, qrid_m.group(1), img


def poll(session, qrid):
    """轮询状态, 返回 (status, cookie_str)。confirmed 时用 alt 换 cookie。"""
    r = session.get(CHECK_URL, params={"entry": "weibo", "qrid": qrid,
                                      "rmlogintatp": "true", "_": int(time.time()*1000)},
                    timeout=15)
    j = r.json()
    retcode = j.get("retcode")
    data = j.get("data") or {}
    # 50044001=未扫码, 50044002/20000000=已扫码待确认/已确认, 50054002=已扫码
    if retcode == 20000000 and data.get("alt"):
        cookie_str = _exchange(session, data["alt"])
        return "confirmed", cookie_str
    if retcode in (50054002, 50054001) or "QRcode_has_scan" in str(j):
        return "scan_by_mobile", None
    if retcode in (50054004,):
        return "expired", None
    return "new", None


def _exchange(session, alt):
    """用 alt 换正式 cookie。"""
    r = session.get(LOGIN_URL,
                    params={"entry": "weibo", "alt": alt,
                            "returntype": "TEXT", "cb": "cb_func"},
                    allow_redirects=False, timeout=20)
    jar = session.cookies.get_dict()
    if "SUB" in jar:
        return "; ".join("%s=%s" % (k, v) for k, v in jar.items())
    # TEXT 模式从 body 里取
    m = re.search(r'"crossdomain_uri":\s*"(.*?)"', r.text)
    if m:
        s2 = _session()
        s2.get(m.group(1).replace("\\/", "/"), allow_redirects=True, timeout=20)
        jar = s2.cookies.get_dict()
        if "SUB" in jar:
            return "; ".join("%s=%s" % (k, v) for k, v in jar.items())
    raise RuntimeError("已确认但未能换取 SUB Cookie, 请改用手动粘贴 Cookie。")
