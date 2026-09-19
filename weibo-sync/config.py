# -*- coding: utf-8 -*-
"""全部通过环境变量配置, 与 docker-compose.yml 中的 environment 对应。"""
import os

KARAKEEP_URL = os.environ.get("KARAKEEP_URL", "http://karakeep:3000").rstrip("/")
KARAKEEP_API_KEY = os.environ.get("KARAKEEP_API_KEY", "")

SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL_SECONDS", "600"))
PAGES_PER_SOURCE = int(os.environ.get("PAGES_PER_SOURCE", "3"))

FAV_TAG = os.environ.get("FAV_TAG", "微博收藏")
LIKE_TAG = os.environ.get("LIKE_TAG", "微博点赞")

STATE_DIR = os.environ.get("STATE_DIR", "/data")
WEB_PORT = int(os.environ.get("WEB_PORT", "9000"))

COOKIE_FILE = os.path.join(STATE_DIR, "cookie.json")
STATE_FILE = os.path.join(STATE_DIR, "state.json")

os.makedirs(STATE_DIR, exist_ok=True)
