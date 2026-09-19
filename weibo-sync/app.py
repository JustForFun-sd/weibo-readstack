# -*- coding: utf-8 -*-
"""
weibo-sync Web 面板 + 后台定时同步。

页面:
  /            状态总览 (登录态 / 上次同步 / 手动触发)
  /login       扫码登录 (手机微博 App 扫码确认)
  /cookie      手动粘贴 Cookie (兜底方案)
  /api/debug   端点校准辅助
"""
import re
import threading
import time
import uuid

from flask import Flask, jsonify, redirect, request

import config
import karakeep
import state
import sync as syncmod
import weibo_api
import weibo_qr

app = Flask(__name__)


@app.after_request
def _cors(resp):
    # 允许油猴脚本跨域推送
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "content-type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

_qr_sessions = {}   # id -> {"s": session, "qrid":..., "done": bool}
_last_report = {"ts": 0, "data": None}


def _wants_json():
    return request.headers.get("content-type", "").startswith("application/json") \
        or request.args.get("fmt") == "json"


def _sanitize_cookie(raw):
    """清洗用户粘贴的 Cookie: 去换行/去 'Cookie:' 前缀/合并空白。"""
    raw = (raw or "").replace("\r", " ").replace("\n", " ").strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[7:]
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


# ---------------- 页面 ----------------

PAGE = """<!doctype html><meta charset=utf-8><title>weibo-sync</title>
<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;
padding:0 16px}pre{background:#f4f4f4;padding:12px;border-radius:8px;
white-space:pre-wrap}</style>"""

INDEX_EXTRA = PAGE + """
<h2>weibo-sync 状态</h2><pre id=st>loading...</pre>
<a href=/login><button>扫码登录微博</button></a>
<a href=/cookie><button>手动粘贴 Cookie</button></a>
<button onclick=run()>立即同步一次</button>
<script>
fetch('/api/status').then(r=>r.json()).then(d=>{
 document.getElementById('st').textContent=JSON.stringify(d,null,2)});
function run(){fetch('/api/run',{method:'POST'}).then(r=>r.json())
 .then(d=>alert('同步完成: '+JSON.stringify(d)));}
</script>"""

LOGIN_EXTRA = PAGE + """
<h2>用手机微博 App 扫码</h2><img id=q width=220 alt="加载中">
<p id=st>等待扫码...</p><a href=/>返回</a><script>
let id='';
fetch('/api/qr/start').then(r=>r.json()).then(d=>{
 if(d.error){document.getElementById('st').textContent='二维码获取失败: '+d.error
 +'  请改用手动粘贴 Cookie';return;}
 id=d.id;document.getElementById('q').src=d.img;poll();});
function poll(){fetch('/api/qr/poll?id='+id).then(r=>r.json()).then(d=>{
 document.getElementById('st').textContent=d.msg;
 if(d.status==='confirmed'){location.href='/';return;}
 if(d.status==='expired'){document.getElementById('st').textContent=
 '二维码已过期, 请刷新页面重试';return;}
 setTimeout(poll,2000);});}
</script>"""

COOKIE_EXTRA = PAGE + """
<h2>手动粘贴 Cookie</h2>
<p>浏览器登录 <b>m.weibo.cn</b> 后, F12 -> Network -> 任意请求 ->
复制整条 <code>Cookie:</code> 请求头的值粘贴到下方（含 SUB、SUBP 等，
可直接整行粘贴，系统会自动清洗）。</p>
<textarea id=ck rows=6 style=width:100%></textarea>
<button onclick=save()>保存并校验</button>
<p id=r></p><a href=/>返回</a><script>
function save(){
 var ck=document.getElementById('ck').value;
 document.getElementById('r').textContent='校验中...';
 fetch('/api/cookie',{method:'POST',headers:{'content-type':'application/json'},
   body:JSON.stringify({cookie:ck})}).then(r=>r.json()).then(d=>{
   document.getElementById('r').textContent=(d.ok?'✅ ':'❌ ')+d.msg;
 }).catch(e=>document.getElementById('r').textContent='请求失败: '+e);}
</script>"""


@app.route("/")
def index():
    return INDEX_EXTRA


@app.route("/login")
def login_page():
    return LOGIN_EXTRA


@app.route("/cookie")
def cookie_page():
    return COOKIE_EXTRA


# ---------------- API ----------------

@app.route("/api/status")
def api_status():
    cookie = state.get_cookie()
    ok, info = weibo_api.validate(cookie) if cookie else (False, "未设置")
    return jsonify({
        "cookie_set": bool(cookie),
        "cookie_valid": ok,
        "cookie_expired": syncmod.cookie_expired(),
        "uid_or_msg": info,
        "karakeep_url": config.KARAKEEP_URL,
        "interval_sec": config.SYNC_INTERVAL,
        "last_sync": {"ts": _last_report["ts"], "report": _last_report["data"]}
        if _last_report["data"] else None,
    })


@app.route("/api/qr/start")
def api_qr_start():
    try:
        s, qrid, img = weibo_qr.start()
    except Exception as e:
        return jsonify({"error": repr(e)})
    sid = uuid.uuid4().hex
    _qr_sessions[sid] = {"s": s, "qrid": qrid, "born": time.time()}
    if img.startswith("//"):
        img = "https:" + img
    return jsonify({"id": sid, "img": img})


@app.route("/api/qr/poll")
def api_qr_poll():
    sess = _qr_sessions.get(request.args.get("id", ""))
    if not sess:
        return jsonify({"status": "expired", "msg": "会话不存在或已过期, 请刷新页面"})
    if time.time() - sess["born"] > 180:
        return jsonify({"status": "expired", "msg": "二维码超时"})
    try:
        status, cookie_str = weibo_qr.poll(sess["s"], sess["qrid"])
    except Exception as e:
        return jsonify({"status": "error", "msg": "轮询异常: %r (可用手动 Cookie 兜底)" % e})
    msg = {"new": "等待扫码...", "scan_by_mobile": "已扫码, 请在手机上点确认",
           "confirmed": "登录成功, Cookie 已保存"}.get(status, status)
    if status == "confirmed" and cookie_str:
        state.set_cookie(cookie_str)
        _qr_sessions.pop(request.args.get("id"), None)
    return jsonify({"status": status, "msg": msg})


@app.route("/api/cookie", methods=["POST"])
def api_cookie():
    raw = request.form.get("cookie") or (request.get_json(silent=True) or {}).get("cookie") or ""
    raw = _sanitize_cookie(raw)
    if not raw:
        return jsonify({"ok": False, "msg": "Cookie 为空"}) if _wants_json() else ("Cookie 为空", 400)
    ok, info = weibo_api.validate(raw)
    if not ok:
        msg = "校验失败: %s" % info
        return (jsonify({"ok": False, "msg": msg}), 400) if _wants_json() else (msg, 400)
    state.set_cookie(raw)
    rep = syncmod.run_once()  # 保存后立刻同步一次, 让用户马上看到效果
    _last_report.update(ts=time.time(), data=rep)
    msg = "登录成功 (uid=%s)，已自动同步：收藏+%s，点赞+%s" % (
        info, rep.get("fav_new", 0), rep.get("like_new", 0))
    if _wants_json():
        return jsonify({"ok": True, "msg": msg, "report": rep})
    return "<meta charset=utf-8><body style='font-family:sans-serif;padding:32px'>" \
           "<h3>✅ %s</h3><a href=/>返回面板</a>" % msg


@app.route("/api/run", methods=["POST"])
def api_run():
    rep = syncmod.run_once()
    _last_report.update(ts=time.time(), data=rep)
    return jsonify(rep)


@app.route("/api/ingest", methods=["POST", "OPTIONS"])
def api_ingest():
    """接收油猴脚本从浏览器直接推送的微博原始 JSON (免 Cookie 主通道)。
    body: {"kind": "fav"|"like", "data": <微博 ajax 原始响应>}"""
    payload = request.get_json(force=True, silent=True) or {}
    kind = payload.get("kind")
    raw = payload.get("data")
    if kind not in ("fav", "like") or not isinstance(raw, dict):
        return jsonify({"pushed": 0, "more": False, "error": "参数不合法"})
    src = weibo_api._statuses_of(raw.get("data") or raw)
    items = [n for n in (weibo_api.normalize(s) for s in src) if n]
    ck = state.get_cookie()
    for x in items:
        try:
            x["content"] = weibo_api.build_content(ck, x)
        except Exception:
            x["content"] = x.get("text") or ""
    seen = state.get_state()[kind]
    new = [x for x in items if x["mid"] not in seen]
    tag = config.FAV_TAG if kind == "fav" else config.LIKE_TAG
    ok, err = 0, ""
    if new:
        ok, err = karakeep.push(new, [tag])
        if ok:
            state.mark_seen(kind, [x["mid"] for x in new])
    return jsonify({"pushed": ok, "seen_total": len(seen) + ok,
                    "more": bool(items), "error": err[:200]})


@app.route("/api/debug")
def api_debug():
    url = request.args.get("url", "")
    if not url.startswith("https://m.weibo.cn/") and not url.startswith("https://weibo.com/"):
        return jsonify({"error": "只允许 m.weibo.cn / weibo.com 域名"})
    return jsonify(weibo_api.debug_raw(state.get_cookie(), url))


# ---------------- 后台循环 ----------------

def _loop():
    time.sleep(15)  # 等容器网络就绪
    while True:
        try:
            rep = syncmod.run_once()
            _last_report.update(ts=time.time(), data=rep)
            if rep["errors"]:
                print("[sync] errors:", rep["errors"])
        except Exception:
            import traceback
            traceback.print_exc()
        time.sleep(config.SYNC_INTERVAL)


threading.Thread(target=_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.WEB_PORT)
