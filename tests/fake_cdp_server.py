#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fake_cdp_server.py — 零依赖假 CDP 服务，用于自测（不联网）。

模拟一个 WebView2/Chromium 目标：
- /json/version 返回 webSocketDebuggerUrl
- /json 返回 page 目标列表
- /json/new?url= 新建目标
- WebSocket 端点实现 harness 实际用到的命令：
  - Runtime.evaluate（用注入的 "页面后端" 返回 DOM 查询值）
  - Page.enable / Page.captureScreenshot（返回符合命名约定的 PNG 字节）

它不渲染真实界面，而是用 harness 的 seed 真值渲染出与真值一致的 DOM 查询
结果，从而把"真实程序渲染 + CDP 驱动"这条链路在自测中用等价后端替代，
同时保持尺寸校验/DPI 换算/artifact manifest 等纯逻辑被真实覆盖。
"""
import base64
import json
import os
import socket
import struct
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sys as _sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from scripts.common import (  # noqa: E402
    encode_png, logical_dpi, expected_physical_size,
)


class FakePageBackend:
    """模拟被测页面：根据 mock_state 返回与真值一致的 DOM 查询值。"""

    def __init__(self, manifest):
        self.manifest = manifest
        expected = manifest.get("expected", {})
        self.expected = expected
        self.title = expected.get("title_text", "示例演示程序")
        self.guest = expected.get("guest_banner_present", False)
        self.login = expected.get("login_prompt_present", False)
        # expected 的 non_interactive_error_bar_hidden 为真表示"应隐藏"
        self.err_visible = not expected.get("non_interactive_error_bar_hidden", True)
        self.tasks = expected.get("task_list", [])

    def query(self, expression):
        # harness 的 cdp_eval 用固定的 JS 片段；这里按片段关键字返回。
        if "document.title" in expression:
            return self.title
        if "data-guest-banner" in expression:
            return self.guest
        if "data-login-prompt" in expression:
            return self.login
        if "data-error-bar" in expression:
            return self.err_visible
        if "data-task-item" in expression:
            return [
                {"id": t.get("id"), "title": t.get("title"),
                 "progress": t.get("progress", 0)}
                for t in self.tasks
            ]
        return None


class FakeCDP:
    def __init__(self, manifest):
        self.manifest = manifest
        self.backend = FakePageBackend(manifest)
        self.lock = threading.Lock()
        self.ws_path = "/fake-ws"
        self.ws_port = 9224
        self.targets = [
            {"id": "fake-page-1", "type": "page", "title": "fake",
             "webSocketDebuggerUrl": "ws://127.0.0.1:%d/fake-ws" % self.ws_port}
        ]

    def version(self):
        return {"Browser": "FakeCDP/1.0",
                "webSocketDebuggerUrl": "ws://127.0.0.1:%d/fake-ws" % self.ws_port}

    def list_targets(self):
        return self.targets

    def new_target(self, url):
        tid = "fake-page-%d" % (len(self.targets) + 1)
        self.targets.append({"id": tid, "type": "page", "title": "fake",
                             "webSocketDebuggerUrl": "ws://127.0.0.1:0/fake-ws"})
        return {"id": tid}

    def handle_command(self, msg):
        method = msg.get("method")
        if method == "Runtime.evaluate":
            expr = msg.get("params", {}).get("expression", "")
            value = self.backend.query(expr)
            return {"result": {"result": {"type": "object", "value": value}}}
        if method == "Page.enable":
            return {"result": {}}
        if method == "Page.captureScreenshot":
            cs = self.manifest.get("content_scale") or 1.0
            lw = self.manifest.get("logical_window", {}).get("width", 0)
            lh = self.manifest.get("logical_window", {}).get("height", 0)
            pw, ph = expected_physical_size(lw, lh, cs)
            # 生成纯色 PNG 字节（仅尺寸有意义，颜色无关）
            pixels = bytes([40, 80, 160]) * (pw * ph)
            png = encode_png(pw, ph, pixels)
            return {"result": {"data": base64.b64encode(png).decode("ascii")}}
        return {"result": {}}


def make_handler(fake):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/json/version":
                return self._send(200, fake.version())
            if parsed.path == "/json":
                return self._send(200, fake.list_targets())
            self.send_response(404); self.end_headers()

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            if parsed.path.startswith("/json/new"):
                url = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
                return self._send(200, fake.new_target(url))
            self.send_response(404); self.end_headers()

        def log_message(self, *a):
            pass
    return Handler


def _ws_send(sock, payload):
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    length = len(data)
    if length < 126:
        header = bytes([0x81, length])
    elif length < 65536:
        header = bytes([0x81, 126]) + struct.pack(">H", length)
    else:
        header = bytes([0x81, 127]) + struct.pack(">Q", length)
    sock.sendall(header + data)


def _ws_recv(sock, timeout=10):
    sock.settimeout(timeout)
    # 读帧头（至少 2 字节）
    head = _recv_exact(sock, 2)
    opcode = head[0] & 0x0F
    masked = bool(head[1] & 0x80)
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _recv_exact(sock, 8))[0]
    if masked:
        mask = _recv_exact(sock, 4)
    payload = _recv_exact(sock, length)
    if masked:
        payload = bytes([b ^ mask[i % 4] for i, b in enumerate(payload)])
    if opcode == 0x8:  # close
        return None
    return payload.decode("utf-8", "replace")


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("WS 连接关闭")
        buf += chunk
    return buf


def _ws_handshake_accept(conn):
    # 读取客户端握手请求直到 \r\n\r\n
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(4096)
        if not chunk:
            return False
        buf += chunk
    resp = ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n\r\n").encode("ascii")
    conn.sendall(resp)
    return True


def _ws_serve_client(conn, fake):
    try:
        if not _ws_handshake_accept(conn):
            return
        while True:
            raw = _ws_recv(conn, timeout=5)
            if raw is None:
                return
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            result = fake.handle_command(msg)
            result["id"] = msg.get("id")
            _ws_send(conn, json.dumps(result))
    except Exception:
        return
    finally:
        try:
            conn.close()
        except Exception:
            pass


def start_ws_server(fake, host="127.0.0.1", port=9224):
    import socket
    ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind((host, port))
    ls.listen(8)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                ls.settimeout(0.5)
                conn, _ = ls.accept()
            except Exception:
                continue
            threading.Thread(target=_ws_serve_client, args=(conn, fake),
                            daemon=True).start()

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return ls, stop


def start(manifest, host="127.0.0.1", port=9223, ws_port=9224):
    fake = FakeCDP(manifest)
    fake.ws_path = "/fake-ws"
    fake.ws_port = ws_port
    srv = ThreadingHTTPServer((host, port), make_handler(fake))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    ls, stop = start_ws_server(fake, host=host, port=ws_port)
    return srv, fake, (ls, stop)


if __name__ == "__main__":
    m = {"content_scale": 3.0, "logical_window": {"width": 1280, "height": 800},
         "expected": {"title_text": "示例演示程序", "guest_banner_present": True,
                      "login_prompt_present": False, "non_interactive_error_bar_hidden": True,
                      "task_list": []}}
    s, f = start(m)
    print("fake cdp on", s.server_address)
    time.sleep(5)
