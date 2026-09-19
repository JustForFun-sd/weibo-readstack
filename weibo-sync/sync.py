# -*- coding: utf-8 -*-
"""一轮完整同步: 拉增量 -> 去重 -> 推送 Karakeep -> 记录游标。"""
import time

import config
import state
import weibo_api


def run_once():
    report = {"ts": time.time(), "ok": False, "fav_new": 0, "like_new": 0,
              "errors": []}

    cookie = state.get_cookie()
    if not cookie:
        report["errors"].append("尚未登录: 请打开 Web 面板扫码或粘贴 Cookie")
        return report

    valid, info = weibo_api.validate(cookie)
    if not valid:
        report["errors"].append("Cookie 已失效(%s): 请重新扫码/粘贴" % info)
        state_flag_expired(True)
        return report
    state_flag_expired(False)

    for source, tag, fetcher in (
        ("fav", config.FAV_TAG, weibo_api.fetch_favorites),
        ("like", config.LIKE_TAG, weibo_api.fetch_likes),
    ):
        try:
            items = fetcher(cookie, pages=config.PAGES_PER_SOURCE)
        except Exception as e:
            report["errors"].append("%s 抓取失败: %r (若持续失败请校准 weibo_api.py 端点)" % (source, e))
            continue
        seen = state.get_state()[source]
        new = [x for x in items if x["mid"] not in seen]
        if new:
            # 内容增强: 抓取正文/长文/图片/文章, 供 Karakeep 直接存档(它无法登录微博抓取)
            for x in new:
                try:
                    x["content"] = weibo_api.build_content(cookie, x)
                except Exception:
                    x["content"] = x.get("text") or x.get("title") or ""
            ok, err = push_with_state(source, tag, new)
            report[source + "_new"] = ok
            if err:
                report["errors"].append(err)
    report["ok"] = True
    return report


def push_with_state(source, tag, new_items):
    ok, err = __import__("karakeep").push(new_items, [tag])
    if ok:
        state.mark_seen(source, [x["mid"] for x in new_items[:ok]])
    return ok, err


# ---- cookie 失效标记(供 Web 面板显示) ----

_expired = {"flag": False}


def state_flag_expired(v):
    _expired["flag"] = bool(v)


def cookie_expired():
    return _expired["flag"]
