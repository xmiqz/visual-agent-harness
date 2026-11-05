#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_host.py — 与本 harness 配套的演示宿主（仅供 example，非 TVG 本体）。

目的：在没有真实 TVG 二进制的机器上，也能端到端验证 harness 全流程。
它读取 harness 约定的环境变量进入"演示/游客态"，从隔离 mock 数据目录
加载任务列表，渲染出与真值清单一致的 DOM（含 data-guest-banner /
data-task-item 等选择器），并以 --remote-debugging-port 暴露自己。

真实接入 TVG 时：把 TVG 的 WebView2 宿主 exe 作为 --program，让其也按
docs/usage.md 的约定读取 VAH_MOCK_DATA_DIR / VAH_CONTENT_SCALE 即可，
无需改动本 harness 任何脚本。

不硬编码真实路径/账号/手机号/IP。
"""
import http.server
import json
import os
import socketserver
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))


def render_html(data_dir):
    state_path = os.path.join(data_dir, "mock_state.json")
    state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    tasks = state.get("tasks", [])
    auth_state = state.get("auth_state", "guest")
    error_bar = state.get("error_bar", {"message": "", "visible": False})

    guest_banner = ""
    login_prompt = ""
    if auth_state == "guest":
        guest_banner = '<div data-guest-banner style="background:#2563EB;color:#fff;padding:8px">游客态演示</div>'
        login_prompt = '<div data-login-prompt style="padding:8px">请登录以同步任务</div>'

    error_bar_html = ""
    if error_bar.get("visible"):
        error_bar_html = '<div data-error-bar style="background:#dc2626;color:#fff;padding:8px">%s</div>' % (
            error_bar.get("message", ""))

    task_items = ""
    for t in tasks:
        task_items += (
            '<div data-task-item data-task-id="%s" data-task-title="%s" '
            'data-task-progress="%d" style="padding:6px;border:1px solid #ccc">'
            '%s — %d%%</div>' % (
                t.get("id", ""), t.get("title", ""), t.get("progress", 0),
                t.get("title", ""), t.get("progress", 0)))

    return """<!doctype html><html><head><meta charset="utf-8">
<title>%s</title></head><body style="margin:0;font-family:sans-serif">
%s%s%s<div data-task-list>%s</div>
</body></html>""" % (
        "示例演示程序", guest_banner, login_prompt, error_bar_html, task_items)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        data_dir = os.environ.get("VAH_MOCK_DATA_DIR", HERE)
        html = render_html(data_dir).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, *args):
        pass


def main(argv=None):
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8901
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
    print("demo_host listening on http://127.0.0.1:%d" % port)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
