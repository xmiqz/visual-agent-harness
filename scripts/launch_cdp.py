#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""launch_cdp.py — 启动被测程序并暴露 Chrome DevTools Protocol 端点。

原则：
- 被测程序路径通过 --program 传入（绝不硬编码）。Windows 上通常是
  WebView2 宿主 exe 或任意 Chromium 内核浏览器。
- 通过 --remote-debugging-port 暴露 CDP；通过独立的 --user-data-dir
  （指向 mock 数据目录的兄弟目录）隔离真实配置/账号。
- 通过环境变量把隔离数据目录与内容缩放传递给被测程序的演示入口
  （约定名见 docs/usage.md），不污染真实安装。
- DPI 感知：被测程序应使用 PerMonitorV2；本脚本仅负责把期望缩放写入
  manifest 并传递给被测程序（--content-scale / 环境变量），真实 DPI
  由操作系统按显示器决定。

纯标准库（subprocess / urllib）。不真实联网、不触碰真实账号。

用法：
  python launch_cdp.py --program EXE --user-data-dir DIR --port 9222 \
      --url URL --data-dir DATA --content-scale 3.0 --session-out SESSION.json
"""
import argparse
import json
import os
import subprocess
import sys
import time

from cdp import get_version, list_targets, new_target, wait_for_port
from common import emit_event, fail, EXIT_ENV, EXIT_INPUT

# 约定：被测程序读取这些环境变量以进入演示/游客态并使用隔离数据。
ENV_DATA_DIR = "VAH_MOCK_DATA_DIR"
ENV_CONTENT_SCALE = "VAH_CONTENT_SCALE"


def build_env(data_dir, content_scale, extra_env=None):
    env = dict(os.environ)
    if data_dir:
        env[ENV_DATA_DIR] = os.path.abspath(data_dir)
    if content_scale is not None:
        env[ENV_CONTENT_SCALE] = str(content_scale)
    if extra_env:
        for k, v in extra_env.items():
            env[k] = v
    return env


def launch(program, user_data_dir, port, url, data_dir, content_scale,
           session_out, headless=False, timeout=30, extra_env=None):
    if not os.path.exists(program):
        fail("被测程序不存在: %s" % program, code=EXIT_ENV, event="env_unavailable")
    os.makedirs(user_data_dir, exist_ok=True)

    cmd = [os.path.abspath(program)]
    # 隔离配置，避免触碰真实账号/安装目录
    cmd += ["--user-data-dir", os.path.abspath(user_data_dir)]
    cmd += ["--remote-debugging-port", str(port)]
    if headless:
        cmd += ["--headless=new"]
    if url:
        cmd += [url]

    env = build_env(data_dir, content_scale, extra_env)
    proc = subprocess.Popen(cmd, env=env)
    emit_event("launched", pid=proc.pid, port=port, program=program)

    if not wait_for_port("127.0.0.1", port, timeout=timeout):
        fail("CDP 端口 %d 未在 %ds 内就绪" % (port, timeout), code=EXIT_ENV,
             event="env_unavailable", pid=proc.pid)

    try:
        ver = get_version("127.0.0.1", port, timeout=10)
    except Exception as exc:
        fail("无法读取 CDP 版本: %s" % exc, code=EXIT_ENV,
             event="env_unavailable", pid=proc.pid)

    targets = list_targets("127.0.0.1", port, timeout=10)
    if not targets:
        fail("CDP 未暴露任何目标", code=EXIT_ENV, event="env_unavailable",
             pid=proc.pid)

    # 若传了 url 且当前无对应 page，可新建；这里直接复用首个 page。
    target_id = targets[0].get("id")
    if url and all(t.get("type") != "page" for t in targets):
        new_target("127.0.0.1", port, url, timeout=10)
        targets = list_targets("127.0.0.1", port, timeout=10)
        target_id = next((t.get("id") for t in targets if t.get("type") == "page"),
                         target_id)

    session = {
        "pid": proc.pid,
        "port": port,
        "host": "127.0.0.1",
        "program": os.path.abspath(program),
        "user_data_dir": os.path.abspath(user_data_dir),
        "data_dir": os.path.abspath(data_dir) if data_dir else None,
        "content_scale": content_scale,
        "target_id": target_id,
        "browser_version": ver.get("Browser"),
        "web_socket_debugger_url": ver.get("webSocketDebuggerUrl"),
    }
    with open(session_out, "w", encoding="utf-8") as fh:
        json.dump(session, fh, ensure_ascii=False, indent=2)
    emit_event("cdp_ready", session=os.path.abspath(session_out),
               browser_version=session["browser_version"],
               target_id=target_id)
    return session


def main(argv=None):
    ap = argparse.ArgumentParser(description="启动被测程序并暴露 CDP 端点")
    ap.add_argument("--program", required=True, help="被测程序可执行文件绝对路径")
    ap.add_argument("--user-data-dir", required=True, help="隔离用户数据目录")
    ap.add_argument("--port", type=int, default=9222, help="CDP 端口")
    ap.add_argument("--url", default="about:blank", help="初始 URL")
    ap.add_argument("--data-dir", default=None, help="隔离 mock 数据目录")
    ap.add_argument("--content-scale", type=float, default=None,
                    help="期望内容缩放(如 3.0=300%)")
    ap.add_argument("--session-out", required=True, help="会话状态输出 JSON")
    ap.add_argument("--headless", action="store_true", help="无头启动")
    ap.add_argument("--timeout", type=int, default=30, help="等待 CDP 就绪秒数")
    ap.add_argument("--set-env", action="append", default=[],
                    help="额外环境变量 KEY=VALUE（可重复）")
    args = ap.parse_args(argv)
    extra = {}
    for kv in args.set_env:
        if "=" not in kv:
            fail("--set-env 需 KEY=VALUE: %s" % kv, code=EXIT_INPUT)
        k, v = kv.split("=", 1)
        extra[k] = v
    launch(args.program, args.user_data_dir, args.port, args.url,
           args.data_dir, args.content_scale, args.session_out,
           headless=args.headless, timeout=args.timeout, extra_env=extra)


if __name__ == "__main__":
    main()
