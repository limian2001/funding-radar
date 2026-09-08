# -*- coding: utf-8 -*-
"""入口：一个采集线程 + 一个 HTTP 服务，单进程单容器。"""
import base64
import hmac
import json
import os
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import core, store, universe as uni_store, web

POLL_SEC = int(os.environ.get("POLL_SEC", "300"))
PORT = int(os.environ.get("PORT", "8080"))
AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASS = os.environ.get("AUTH_PASS", "")
MAX_BODY = 64 * 1024

# 加了标的之后立刻催一次采集，不用干等一个轮询周期
WAKE = threading.Event()


def collector():
    while True:
        t0 = time.time()
        try:
            n_legs, n_pairs, health = core.run_once()
            bad = [v for v, h in health.items() if not h.get("ok")]
            print("[collect] legs=%d pairs=%d %s" % (
                n_legs, n_pairs, ("失败: " + ",".join(bad)) if bad else "ok"),
                flush=True)
        except Exception:
            traceback.print_exc()
        WAKE.wait(max(5, POLL_SEC - (time.time() - t0)))
        WAKE.clear()


class H(BaseHTTPRequestHandler):
    server_version = "radar"
    sys_version = ""

    # ---------------------------------------------------------- 基础
    def _send(self, code, body, ctype, extra=None):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _json(self, obj, code=200):
        self._send(code, obj if isinstance(obj, str)
                   else json.dumps(obj, ensure_ascii=False),
                   "application/json; charset=utf-8")

    def _authed(self):
        if not AUTH_PASS:
            return True
        h = self.headers.get("Authorization", "")
        if not h.startswith("Basic "):
            return False
        try:
            got = base64.b64decode(h[6:].strip())
        except Exception:
            return False
        # 必须用 bytes 比较：compare_digest 传 str 只接受纯 ASCII
        want = ("%s:%s" % (AUTH_USER, AUTH_PASS)).encode("utf-8")
        return hmac.compare_digest(got, want)

    def _deny(self):
        self._send(401, "unauthorized", "text/plain",
                   {"WWW-Authenticate": 'Basic realm="funding-radar"'})

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    # ---------------------------------------------------------- 路由
    def do_GET(self):
        try:
            path, _, qs = self.path.partition("?")
            q = urllib.parse.parse_qs(qs)
            if path.startswith("/healthz"):
                return self._send(200, "ok", "text/plain")
            if not self._authed():
                return self._deny()
            if path.startswith("/api/latest"):
                return self._json(web.api_latest(POLL_SEC))
            if path.startswith("/api/search"):
                return self._json(web.api_search((q.get("q") or [""])[0]))
            if path.startswith("/api/stock"):
                return self._json(web.api_stock((q.get("market") or [""])[0],
                                                (q.get("code") or [""])[0]))
            self._send(200, web.shell(), "text/html; charset=utf-8")
        except Exception:
            traceback.print_exc()
            try:
                self._send(500, "internal error - 看 docker compose logs",
                           "text/plain; charset=utf-8")
            except Exception:
                pass

    def do_POST(self):
        try:
            if not self._authed():
                return self._deny()
            path = self.path.split("?")[0]
            d = self._body()
            if path == "/api/universe/add":
                key = uni_store.add_asset(
                    d.get("key"), d.get("name"), d.get("underlying"),
                    d.get("venues"))
                WAKE.set()                      # 立刻采一轮
                print("[universe] 添加 %s，已触发立即采集" % key, flush=True)
                return self._json({"ok": True, "key": key})
            if path == "/api/universe/order":
                return self._json({"ok": True,
                                   "order": uni_store.set_order(d.get("order"))})
            if path == "/api/universe/remove":
                ok = uni_store.remove_asset(d.get("key"))
                WAKE.set()
                print("[universe] 删除 %s -> %s" % (d.get("key"), ok), flush=True)
                return self._json({"ok": ok})
            self._json({"error": "未知接口"}, 404)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            self._json({"error": str(e)[:200]}, 500)

    def log_message(self, *a):
        pass


def main():
    store.init()
    uni_store.ensure_seeded()
    if AUTH_PASS:
        print("[web] 已启用 Basic Auth，用户名 %s" % AUTH_USER, flush=True)
    else:
        print("[web] !! 未设置 AUTH_PASS，页面无口令保护。"
              "若已对公网开放，请务必在安全组里把来源限制为你的固定 IP。",
              flush=True)
    print("[web] 标的清单: %s" % uni_store.LIVE_PATH, flush=True)
    threading.Thread(target=collector, daemon=True).start()
    print("[web] listening on :%d  轮询间隔 %ds" % (PORT, POLL_SEC), flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()


if __name__ == "__main__":
    main()
