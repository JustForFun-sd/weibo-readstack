# -*- coding: utf-8 -*-
"""Cookie 与增量游标的本地持久化。"""
import json
import os
import time

import config


def _load(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


# ---------------- Cookie ----------------

def get_cookie():
    return _load(config.COOKIE_FILE).get("cookie", "")


def set_cookie(cookie_str):
    _save(config.COOKIE_FILE, {"cookie": cookie_str.strip(), "ts": time.time()})


# ---------------- 已见 mid 集合 ----------------

def get_state():
    st = _load(config.STATE_FILE)
    st.setdefault("fav", {})   # mid -> 首次见到时间戳
    st.setdefault("like", {})
    return st


def mark_seen(source, mids):
    st = get_state()
    now = time.time()
    for m in mids:
        st[source][m] = now
    # 防止无限膨胀: 每个来源只保留最近 20000 条
    if len(st[source]) > 20000:
        keep = sorted(st[source].items(), key=lambda kv: kv[1])[-20000:]
        st[source] = dict(keep)
    _save(config.STATE_FILE, st)
