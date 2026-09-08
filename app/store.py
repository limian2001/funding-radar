# -*- coding: utf-8 -*-
"""SQLite 存储。用 sqlite 而不是 CSV，是因为我们要回答的是
「机会持续多久」「基差波动多大」，这些都需要时间序列查询。"""
import os
import sqlite3
import threading
import time

DB_PATH = os.environ.get("DB_PATH", "/data/radar.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS leg (
  ts INTEGER NOT NULL, asset TEXT NOT NULL, venue TEXT NOT NULL,
  symbol TEXT NOT NULL, rate REAL, interval_h REAL, apr REAL, mark REAL
);
CREATE INDEX IF NOT EXISTS idx_leg_ts ON leg(ts);
CREATE INDEX IF NOT EXISTS idx_leg_asset ON leg(asset, ts);

CREATE TABLE IF NOT EXISTS pair (
  ts INTEGER NOT NULL, asset TEXT NOT NULL,
  long_venue TEXT, long_apr REAL, short_venue TEXT, short_apr REAL,
  net_apr REAL, mark_spread_pct REAL, n_legs INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pair_ts ON pair(ts);
CREATE INDEX IF NOT EXISTS idx_pair_asset ON pair(asset, ts);

CREATE TABLE IF NOT EXISTS health (
  ts INTEGER NOT NULL, venue TEXT NOT NULL, ok INTEGER, n INTEGER, err TEXT
);
"""

# 后加的列，用 ALTER 逐个补，老库也能直接升级
EXTRA_COLS = {
    "leg": [("last", "REAL"), ("bid", "REAL"), ("bid_sz", "REAL"),
            ("ask", "REAL"), ("ask_sz", "REAL"), ("next_ts", "INTEGER"),
            ("premium_pct", "REAL")],
    "pair": [("anchor_usd", "REAL"), ("stock_price", "REAL"), ("ccy", "TEXT"),
             ("fx", "REAL"), ("stock_name", "TEXT"), ("quote_time", "TEXT"),
             ("best_prem_venue", "TEXT"), ("best_prem_pct", "REAL"),
             ("worst_prem_venue", "TEXT"), ("worst_prem_pct", "REAL")],
}


def _conn():
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    with _lock, _conn() as c:
        c.executescript(SCHEMA)
        for table, cols in EXTRA_COLS.items():
            have = {r["name"] for r in c.execute("PRAGMA table_info(%s)" % table)}
            for name, typ in cols:
                if name not in have:
                    c.execute("ALTER TABLE %s ADD COLUMN %s %s"
                              % (table, name, typ))


def _cols(table):
    with _conn() as c:
        return [r["name"] for r in c.execute("PRAGMA table_info(%s)" % table)]


def write_round(ts, legs, pairs, health):
    lc = [c for c in _cols("leg") if c not in ("ts", "asset")]
    pc = [c for c in _cols("pair") if c not in ("ts", "asset")]
    with _lock, _conn() as c:
        if legs:
            c.executemany(
                "INSERT INTO leg(ts,asset,%s) VALUES(?,?,%s)"
                % (",".join(lc), ",".join("?" * len(lc))),
                [tuple([ts, l["asset"]] + [l.get(k) for k in lc]) for l in legs])
        if pairs:
            c.executemany(
                "INSERT INTO pair(ts,asset,%s) VALUES(?,?,%s)"
                % (",".join(pc), ",".join("?" * len(pc))),
                [tuple([ts, p["asset"]] + [p.get(k) for k in pc]) for p in pairs])
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
        return ts, [dict(r) for r in c.execute(
            "SELECT * FROM pair WHERE ts=? ORDER BY asset", (ts,)).fetchall()]


def latest_legs(asset):
    with _conn() as c:
        row = c.execute("SELECT MAX(ts) t FROM leg WHERE asset=?",
                        (asset,)).fetchone()
        if not row or row["t"] is None:
            return []
        return [dict(r) for r in c.execute(
            "SELECT * FROM leg WHERE asset=? AND ts=? ORDER BY apr",
            (asset, row["t"])).fetchall()]


def latest_health():
    with _conn() as c:
        row = c.execute("SELECT MAX(ts) t FROM health").fetchone()
        if not row or row["t"] is None:
            return []
        return [dict(r) for r in c.execute(
            "SELECT * FROM health WHERE ts=?", (row["t"],)).fetchall()]


def history(asset, limit=500):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT ts,net_apr,mark_spread_pct,best_prem_pct FROM pair"
            " WHERE asset=? ORDER BY ts DESC LIMIT ?",
            (asset, limit)).fetchall()][::-1]


def trailing(asset, hours=24, threshold=10.0):
    """过去 N 小时的真实表现。比「此刻的年化」诚实：瞬时年化是把一个
    1 小时的费率外推 8760 小时，几乎必然失真。"""
    since = int(time.time()) - hours * 3600
    with _conn() as c:
        r = c.execute(
            "SELECT COUNT(*) n, AVG(net_apr) avg_net, MIN(net_apr) min_net,"
            " MAX(net_apr) max_net, MIN(mark_spread_pct) min_basis,"
            " MAX(mark_spread_pct) max_basis,"
            " MIN(best_prem_pct) min_prem, MAX(best_prem_pct) max_prem,"
            " SUM(CASE WHEN net_apr >= ? THEN 1 ELSE 0 END) n_above"
            " FROM pair WHERE asset=? AND ts>=? AND net_apr IS NOT NULL",
            (threshold, asset, since)).fetchone()
        d = dict(r) if r else {}
        n = d.get("n") or 0
        d["pct_above"] = (100.0 * (d.get("n_above") or 0) / n) if n else None
        return d
