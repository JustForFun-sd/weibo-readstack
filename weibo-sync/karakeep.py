# -*- coding: utf-8 -*-
"""
Karakeep Public API 推送 (适配 v0.33: 单条创建 POST /api/v1/bookmarks)。

请求体为按 type 判别的 union:
  {"type":"link","url":..,"note":..,"tagIds":[..]}
标签需先用 name 解析成 id (GET /api/v1/tags), 不存在则创建。
"""
import requests

import config

_tag_cache = {}   # name -> id


def _headers():
    return {"Authorization": "Bearer " + config.KARAKEEP_API_KEY,
            "Content-Type": "application/json"}


def _api(path):
    return config.KARAKEEP_URL + "/api/v1" + path


def resolve_tag_ids(names):
    """把标签名解析为 id 列表, 缺失的自动创建。结果缓存于进程内。"""
    ids = []
    for name in names:
        if name in _tag_cache:
            ids.append(_tag_cache[name])
            continue
        tid = None
        cursor = None
        while True:                      # 分页查找
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            r = requests.get(_api("/tags"), headers=_headers(), params=params, timeout=20)
            if r.status_code != 200:
                break
            data = r.json()
            for t in data.get("tags", []):
                if t.get("name") == name:
                    tid = t["id"]
                    break
            if tid or not data.get("nextCursor"):
                break
            cursor = data.get("nextCursor")
        if tid is None:                  # 不存在则创建
            r = requests.post(_api("/tags"), headers=_headers(),
                              json={"name": name}, timeout=20)
            if r.status_code in (200, 201):
                tid = r.json().get("id")
        if tid:
            _tag_cache[name] = tid
            ids.append(tid)
    return ids


def push(items, tags):
    """items: [{mid,title,text,url}], 逐条创建 link 书签; 返回 (成功数, 首个错误)。"""
    if not items:
        return 0, ""
    if not config.KARAKEEP_API_KEY:
        return 0, "KARAKEEP_API_KEY 未配置"
    tag_ids = resolve_tag_ids(tags)
    marker = "".join("[%s]" % t for t in tags)  # 该 API 版本不能在创建时挂标签, 用正文前缀标记来源
    ok, err = 0, ""
    for x in items:
        content = x.get("content") or x.get("text") or x.get("title") or ""
        # 微博页 Karakeep 自身无法登录抓取, 故作为文本书签把完整内容直接写入, 原文链接附在文末
        body = {
            "type": "text",
            "text": (marker + "\n\n" + content)[:12000],
            "title": (x.get("title") or content[:40])[:120],
            "tagIds": tag_ids,
        }
        try:
            r = requests.post(_api("/bookmarks"), headers=_headers(), json=body, timeout=45)
            if r.status_code in (200, 201):
                ok += 1
            else:
                err = "%s: %s" % (r.status_code, r.text[:200])
        except Exception as e:
            err = repr(e)
    return ok, err
