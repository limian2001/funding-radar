# -*- coding: utf-8 -*-
"""标的清单的读写。

config/universe.json 是「种子」（在 git 里，只读挂载）；
运行时真正生效的是 /data/universe.json（可写卷），页面上的设置会写它。
第一次启动时若可写副本不存在，就从种子拷一份。
这样既能用页面增删标的，也保留了改 git 配置的老路子。
"""
import json
import os
import shutil
import threading

SEED_PATH = os.environ.get("UNIVERSE_PATH", "/app/config/universe.json")
LIVE_PATH = os.environ.get("UNIVERSE_LIVE", "/data/universe.json")
_lock = threading.Lock()

VALID_MARKETS = {"A", "HK", "US"}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ensure_seeded():
    if os.path.exists(LIVE_PATH):
        return
    d = os.path.dirname(LIVE_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    try:
        shutil.copyfile(SEED_PATH, LIVE_PATH)
    except Exception:
        with open(LIVE_PATH, "w", encoding="utf-8") as f:
            json.dump({"_fx": {"CNH": None, "HKD": None}}, f)


def load_raw():
    ensure_seeded()
    for p in (LIVE_PATH, SEED_PATH):
        try:
            return _read(p)
        except Exception:
            continue
    return {}


def save_raw(d):
    with _lock:
        tmp = LIVE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, LIVE_PATH)      # 原子替换，避免写一半被读到


def parsed():
    """返回 (universe, fx_override)。兼容新旧两种写法。"""
    raw = load_raw()
    fx = raw.get("_fx") or {}
    uni = {}
    for k, v in raw.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        if "venues" in v:
            uni[k] = {"name": v.get("name", k),
                      "underlying": v.get("underlying"),
                      "venues": {a: b for a, b in v["venues"].items()
                                 if not a.startswith("_") and b}}
        else:
            uni[k] = {"name": k, "underlying": None,
                      "venues": {a: b for a, b in v.items()
                                 if not a.startswith("_") and b}}
    return uni, fx


def add_asset(key, name, underlying, venues_map):
    key = (key or "").strip().upper()
    if not key or key.startswith("_"):
        raise ValueError("标的代号不能为空，也不能以下划线开头")
    venues_map = {k: v.strip() for k, v in (venues_map or {}).items()
                  if v and v.strip()}
    if not venues_map:
        raise ValueError("至少要选一个交易所的合约")
    u = None
    if underlying and underlying.get("code"):
        m = (underlying.get("market") or "").upper()
        if m not in VALID_MARKETS:
            raise ValueError("市场只能是 A / HK / US")
        u = {"market": m, "code": str(underlying["code"]).strip()}
    raw = load_raw()
    raw[key] = {"name": (name or key).strip(), "underlying": u,
                "venues": venues_map}
    save_raw(raw)
    return key


def remove_asset(key):
    raw = load_raw()
    if key in raw:
        del raw[key]
        save_raw(raw)
        return True
    return False
