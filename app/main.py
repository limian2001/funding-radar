# -*- coding: utf-8 -*-
"""入口：一个采集线程 + 一个 HTTP 服务，单进程单容器。"""
import base64
import hmac
import os
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import core, store, web

POLL_SEC = int(os.environ.get("POLL_SEC", "300"))
PORT = int(os.environ.get("PORT", "8080"))
AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASS = os.environ.get("AUTH_PASS", "")


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
        time.sleep(max(5, POLL_SEC - (time.time() - t0)))


class H(BaseHTTPRequestHandler):
    server_version = "radar"
    sys_version = ""

    def _send(self, code, body, ctype, extra=None):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _authed(self):
        if not AUTH_PASS:              # 没设密码就不校验
            return True
        h = self.headers.get("Authorization", "")
        if not h.startswith("Basic "):
            return False
        try:
            got = base64.b64decode(h[6:].strip())
        except Exception:
            return False
        # 必须用 bytes 比较：hmac.compare_digest 传 str 时只接受纯 ASCII，
        # 密码里带中文或任何非 ASCII 字符会抛 TypeError -> 500。
        want = ("%s:%s" % (AUTH_USER, AUTH_PASS)).encode("utf-8")
        return hmac.compare_digest(got, want)

    def do_GET(self):
        try:
            if self.path.startswith("/healthz"):          # 探针不校验
                return self._send(200, "ok", "text/plain")
            if not self._authed():
                return self._send(
                    401, "unauthorized", "text/plain",
                    {"WWW-Authenticate": 'Basic realm="funding-radar"'})
            if self.path.startswith("/api/latest"):
                self._send(200, web.api_latest(),
                           "application/json; charset=utf-8")
            elif self.path.startswith("/a/"):
                asset = urllib.parse.unquote(
                    self.path[3:].split("?")[0].strip("/"))
                self._send(200, web.render_asset(asset),
                           "text/html; charset=utf-8")
            else:
                self._send(200, web.render(), "text/html; charset=utf-8")
        except Exception:
            # 打完整堆栈到日志，页面只回一句话
            traceback.print_exc()
            try:
                self._send(500, "internal error - 看 docker compose logs",
                           "text/plain; charset=utf-8")
            except Exception:
                pass

    def log_message(self, *a):
        pass


def main():
    store.init()
    if AUTH_PASS:
        print("[web] 已启用 Basic Auth，用户名 %s" % AUTH_USER, flush=True)
    else:
        print("[web] !! 未设置 AUTH_PASS，页面无口令保护。"
              "若已对公网开放，请务必在安全组里把来源限制为你的固定 IP。",
              flush=True)
    threading.Thread(target=collector, daemon=True).start()
    print("[web] listening on :%d  轮询间隔 %ds" % (PORT, POLL_SEC), flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()


if __name__ == "__main__":
    main()
