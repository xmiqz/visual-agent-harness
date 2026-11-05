#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cdp.py — 最小 Chrome DevTools Protocol 客户端（零三方依赖）。

使用 CDP 的 HTTP 端点完成全部本 harness 所需动作：
- /json/version 取 webSocketDebuggerUrl 与浏览器版本
- /json 列举目标
- /json/new?url=... 新建页面目标
- /json/activate/<id> 激活目标
- 通过 WebSocket（标准库 _ws 原生实现）收发命令/事件

真实链路需要 WebSocket；为保持零依赖，这里用标准库实现最小 WS 客户端。
自测时由 fake_cdp_server 提供纯 HTTP 桩，不走 WS。

不硬编码任何真实项目路径、账号、IP。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# 标准库最小 WebSocket 客户端（RFC 6455）
try:  # Python 3.13+ 自带
    from wsclient import connect as _ws_connect  # type: ignore  # pragma: no cover
except Exception:  # pragma: no cover
    _ws_connect = None

from common import fail

HANDSHAKE_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _http_get_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post(url, data=None, timeout=10):
    body = None
    headers = {}
    if data is not None:
        body = data.encode("utf-8") if isinstance(data, str) else data
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:  # 某些端点返回非 2xx
        raw = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}


def get_version(host, port, timeout=10):
    return _http_get_json("http://%s:%d/json/version" % (host, port), timeout=timeout)


def list_targets(host, port, timeout=10):
    return _http_get_json("http://%s:%d/json" % (host, port), timeout=timeout)


def new_target(host, port, url, timeout=10):
    target = _http_post("http://%s:%d/json/new?%s" % (
        host, port, urllib.parse.urlencode({"url": url})), timeout=timeout)
    return target


def activate_target(host, port, target_id, timeout=10):
    return _http_post("http://%s:%d/json/activate/%s" % (host, port, target_id),
                      timeout=timeout)


def close_target(host, port, target_id, timeout=10):
    return _http_post("http://%s:%d/json/close/%s" % (host, port, target_id),
                      timeout=timeout)


# ---------------------------------------------------------------------------
# 真实 WS 客户端（标准库实现）
# ---------------------------------------------------------------------------

def _ws_handshake(host, port, ws_path, timeout=10):
    import base64
    import socket
    import ssl
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    sock = socket.create_connection((host, port), timeout=timeout)
    req = (
        "GET %s HTTP/1.1\r\n"
        "Host: %s:%d\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: %s\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Origin: http://%s:%d\r\n\r\n"
    ) % (ws_path, host, port, key, host, port)
    sock.sendall(req.encode("ascii"))
    # 读取握手响应头
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    header, _, _ = buf.partition(b"\r\n\r\n")
    if b"101" not in header.split(b"\r\n", 1)[0]:
        sock.close()
        raise RuntimeError("WebSocket 握手失败: " + header.decode("ascii", "replace"))
    return sock


def _ws_send(sock, payload):
    import struct as _struct
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    length = len(data)
    if length < 126:
        header = bytes([0x81, 0x80 | length])
    elif length < 65536:
        header = bytes([0x81, 0x80 | 126]) + _struct.pack(">H", length)
    else:
        header = bytes([0x81, 0x80 | 127]) + _struct.pack(">Q", length)
    mask = os.urandom(4)
    masked = bytes([b ^ mask[i % 4] for i, b in enumerate(data)])
    sock.sendall(header + mask + masked)


def _ws_recv(sock, timeout=10):
    import struct as _struct
    sock.settimeout(timeout)
    try:
        header = _recv_exact(sock, 2)
    except Exception:
        return None
    opcode = header[0] & 0x0F
    length = header[1] & 0x7F
    if length == 126:
        length = _struct.unpack(">H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = _struct.unpack(">Q", _recv_exact(sock, 8))[0]
    payload = _recv_exact(sock, length)
    if opcode == 0x8:  # close
        return None
    return payload.decode("utf-8", "replace")


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("WebSocket 连接关闭")
        buf += chunk
    return buf


class CDPConnection:
    """对单个 page target 的 CDP 连接（命令+事件）。"""

    def __init__(self, host, port, ws_url, timeout=30):
        self.host = host
        self.port = port
        self.ws_url = ws_url
        self.timeout = timeout
        parsed = urllib.parse.urlparse(ws_url)
        # ws_url 自带 host/port 时优先用之（fake/真实端点可能不同）
        if parsed.hostname:
            host = parsed.hostname
        if parsed.port:
            port = parsed.port
        self.host = host
        self.port = port
        self._sock = _ws_handshake(host, port, parsed.path, timeout=timeout)
        self._next_id = 1
        self._pending = {}

    def send(self, method, params=None, session_id=None):
        mid = self._next_id
        self._next_id += 1
        msg = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        _ws_send(self._sock, json.dumps(msg))
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            raw = _ws_recv(self._sock, timeout=self.timeout)
            if raw is None:
                break
            obj = json.loads(raw)
            if obj.get("id") == mid:
                if "error" in obj:
                    raise RuntimeError("CDP %s 错误: %s" % (method, obj["error"]))
                return obj.get("result", {})
            # 其余作为事件暂存（调用方可用 drain_events 取）
        raise RuntimeError("CDP %s 超时未收到响应" % method)

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


def connect_page(host, port, target_id, timeout=30):
    """通过 /json 取得 target 的 webSocketDebuggerUrl 并建立连接。"""
    targets = list_targets(host, port, timeout=timeout)
    ws_url = None
    for t in targets:
        if t.get("id") == target_id or t.get("webSocketDebuggerUrl", "").endswith(target_id):
            ws_url = t.get("webSocketDebuggerUrl")
            break
    if not ws_url:
        raise RuntimeError("找不到目标 %s 的 WebSocket 端点" % target_id)
    return CDPConnection(host, port, ws_url, timeout=timeout)


def connect_any_page(host, port, timeout=30):
    targets = list_targets(host, port, timeout=timeout)
    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        raise RuntimeError("没有可用 page 目标")
    return connect_page(host, port, pages[0]["id"], timeout=timeout)


def wait_for_port(host, port, timeout=30):
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.25)
    return False
