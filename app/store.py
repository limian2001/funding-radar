# -*- coding: utf-8 -*-
"""SQLite 存储。用 sqlite 而不是 CSV，是因为我们真正要回答的问题是
「机会持续多久」「基差波动多大」，这些都需要按时间序列查询。"""
import os
import sqlite3
import threading

DB_PATH = os.environ.get("DB_PATH", "/data/radar.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS leg (
  ts INTEGER NOT NULL,
  asset TEXT NOT NULL,
  venue TEXT NOT NULL,
  symbol TEXT NOT NULL,
  rate REAL, interval_h REAL, apr REAL, mark REAL
);
CREATE INDEX IF NOT EXISTS idx_leg_ts ON leg(ts);
CREATE INDEX IF NOT EXISTS idx_leg_asset ON leg(asset, ts);

CREATE TABLE IF NOT EXISTS pair (
  ts INTEGER NOT NULL,
  asset TEXT NOT NULL,
  long_venue TEXT, long_apr REAL,
  short_venue TEXT, short_apr REAL,
  net_apr REAL,
  mark_spread_pct REAL,
  n_legs INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pair_ts ON pair(ts);
CREATE INDEX IF NOT EXISTS idx_pair_asset ON pair(asset, ts);

CREATE TABLE IF NOT EXISTS health (
  ts INTEGER NOT NULL,
  venue TEXT NOT NULL,
  ok INTEGER, n INTEGER, err TEXT
);
"""


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    with _lock, _conn() as c:
        c.executescript(SCHEMA)


def write_round(ts, legs, pairs, health):
    with _lock, _conn() as c:
        c.executemany(
            "INSERT INTO leg(ts,asset,venue,symbol,rate,interval_h,apr,mark)"
            " VALUES(?,?,?,?,?,?,?,?)",
            [(ts, l["asset"], l["venue"], l["symbol"], l["rate"],
              l["interval_h"], l["apr"], l["mark"]) for l in legs])
        c.executemany(
            "INSERT INTO pair(ts,asset,long_venue,long_apr,short_venue,"
            "short_apr,net_apr,mark_spread_pct,n_legs) VALUES(?,?,?,?,?,?,?,?,?)",
            [(ts, p["asset"], p["long_venue"], p["long_apr"], p["short_venue"],
              p["short_apr"], p["net_apr"], p["mark_spread_pct"], p["n_legs"])
             for p in pairs])
        c.executemany(
            "INSERT INTO health(ts,venue,ok,n,err) VALUES(?,?,?,?,?)",
            [(ts, v, 1 if h.get("ok") else 0, h.get("n", 0), h.get("err", ""))
             for v, h in health.items()])


def latest_pairs():
    with _conn() as c:
        row = c.execute("SELECT MAX(ts) t FROM pair").fetchone()
        if not row or row["t"] is None:
            return 0, []
        ts = row["t"]
        rows = c.execute(
            "SELECT * FROM pair WHERE ts=? ORDER BY net_apr DESC", (ts,)
        ).fetchall()
        return ts, [dict(r) for r in rows]


def latest_legs(asset):
    with _conn() as c:
        row = c.execute("SELECT MAX(ts) t FROM leg WHERE asset=?",
                        (asset,)).fetchone()
        if not row or row["t"] is None:
            return []
        return [dict(r) for r in c.execute(
            "SELECT * FROM leg WHERE asset=? AND ts=? ORDER BY apr",
            (asset, row["t"])).fetchall()]


def history(asset, limit=500):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT ts,net_apr,mark_spread_pct FROM pair WHERE asset=?"
            " ORDER BY ts DESC LIMIT ?", (asset, limit)).fetchall()][::-1]


def stats(asset, since_ts):
    """机会质量的三个数：出现频率、净年化分布、基差波动。"""
    with _conn() as c:
        r = c.execute(
            "SELECT COUNT(*) n, AVG(net_apr) avg_net, MAX(net_apr) max_net,"
            " MIN(net_apr) min_net, AVG(ABS(mark_spread_pct)) avg_basis,"
            " MAX(ABS(mark_spread_pct)) max_basis"
            " FROM pair WHERE asset=? AND ts>=?", (asset, since_ts)).fetchone()
        return dict(r) if r else {}


def latest_health():
    with _conn() as c:
        row = c.execute("SELECT MAX(ts) t FROM health").fetchone()
        if not row or row["t"] is None:
            return []
        return [dict(r) for r in c.execute(
            "SELECT * FROM health WHERE ts=?", (row["t"],)).fetchall()]


def trailing(asset, hours=24, threshold=10.0):
    """过去 N 小时的真实表现。比「此刻的年化」诚实得多：
    瞬时年化是把一个 1 小时的费率外推 8760 小时，几乎必然失真；
    真正该看的是这段时间里它平均多少、波动多大、有多少比例的时刻站得住。"""
    import time as _t
    since = int(_t.time()) - hours * 3600
    with _conn() as c:
        r = c.execute(
            "SELECT COUNT(*) n,"
            " AVG(net_apr) avg_net, MIN(net_apr) min_net, MAX(net_apr) max_net,"
            " MIN(mark_spread_pct) min_basis, MAX(mark_spread_pct) max_basis,"
            " SUM(CASE WHEN net_apr >= ? THEN 1 ELSE 0 END) n_above"
            " FROM pair WHERE asset=? AND ts>=? AND net_apr IS NOT NULL",
            (threshold, asset, since)).fetchone()
        d = dict(r) if r else {}
        n = d.get("n") or 0
        d["pct_above"] = (100.0 * (d.get("n_above") or 0) / n) if n else None
        d["basis_range"] = ((d["max_basis"] - d["min_basis"])
                            if d.get("max_basis") is not None
                            and d.get("min_basis") is not None else None)
        return d
