#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cdp_eval.py — 通过 CDP 驱动被测页面，做交互/内容自动验收。

验收项（全部来自 seed 阶段生成的真值 manifest，不臆造）：
- 访客横幅 / 登录提示存在性
- 任务列表条目数与进度（DOM 查询）
- 非交互错误条是否隐藏（DOM 可见性）
- 标题文本

真实链路用 WebSocket 注入 Runtime.evaluate 查询 DOM；自测由 harness
传入一个"页面后端"，它暴露与被测页等价的查询接口（见 tests/smoke_test）。

纯标准库。不触碰真实账号、不硬编码项目路径。

用法：
  python cdp_eval.py --session SESSION.json --manifest MANIFEST.json \
      --report-out REPORT.json
"""
import argparse
import json
import os
import sys

from cdp import connect_any_page
from common import emit_event, fail, EXIT_ENV, EXIT_INPUT


def _runtime_query(conn, expression):
    """对真实 page 注入一段 Runtime.evaluate，返回 JSON 序列化结果。"""
    result = conn.send("Runtime.evaluate",
                       {"expression": expression, "returnByValue": True})
    exc = result.get("exceptionDetails")
    if exc:
        raise RuntimeError("页面求值异常: %s" % exc.get("text"))
    return result.get("result", {}).get("value")


def evaluate_page(backend, manifest):
    """backend: 真实连接或测试桩，提供 query(js_string) -> python 值。

    返回 (checks, passed) 其中 checks 为逐项结果列表。
    """
    expected = manifest.get("expected", {})
    checks = []

    def add(name, ok, detail=None):
        item = {"name": name, "pass": bool(ok)}
        if detail is not None:
            item["detail"] = detail
        checks.append(item)

    # 标题
    title = backend.query("document.title")
    add("title_text", title == expected.get("title_text"),
        {"expected": expected.get("title_text"), "actual": title})

    # 访客横幅
    guest_q = ("(function(){var e=document.querySelector('[data-guest-banner]');"
               "return !!e && e.offsetParent !== null;})()")
    guest = backend.query(guest_q)
    add("guest_banner_present", guest == expected.get("guest_banner_present"),
        {"expected": expected.get("guest_banner_present"), "actual": guest})

    # 登录提示
    login_q = ("(function(){var e=document.querySelector('[data-login-prompt]');"
               "return !!e && e.offsetParent !== null;})()")
    login = backend.query(login_q)
    add("login_prompt_present", login == expected.get("login_prompt_present"),
        {"expected": expected.get("login_prompt_present"), "actual": login})

    # 非交互错误条隐藏：expected 为真表示"应隐藏"，故可见性应为相反值
    err_q = ("(function(){var e=document.querySelector('[data-error-bar]');"
             "return !!e && e.offsetParent !== null;})()")
    err_visible = backend.query(err_q)
    expected_hidden = expected.get("non_interactive_error_bar_hidden", True)
    add("non_interactive_error_bar_hidden",
        err_visible == (not expected_hidden),
        {"expected_hidden": expected_hidden, "actual_visible": err_visible})

    # 任务列表
    tasks_q = ("(function(){var items=document.querySelectorAll('[data-task-item]');"
               "return Array.prototype.map.call(items,function(n){"
               "return {id:n.getAttribute('data-task-id'),"
               "title:n.getAttribute('data-task-title')||n.textContent.trim(),"
               "progress:parseInt(n.getAttribute('data-task-progress')||'0',10)};});"
               "})()")
    tasks = backend.query(tasks_q) or []
    expected_tasks = expected.get("task_list", [])
    same = len(tasks) == len(expected_tasks)
    if same:
        for a, b in zip(tasks, expected_tasks):
            if a.get("id") != b.get("id") or a.get("title") != b.get("title") \
                    or a.get("progress") != b.get("progress"):
                same = False
                break
    add("task_list", same, {"expected": expected_tasks, "actual": tasks})

    passed = all(c["pass"] for c in checks)
    return checks, passed


def run(session_path, manifest_path, report_out):
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(session_path, "r", encoding="utf-8") as fh:
        session = json.load(fh)

    if not os.path.exists(session_path):
        fail("会话文件不存在", code=EXIT_ENV)

    # 真实链路：建立 WS 连接并包装为 backend
    try:
        conn = connect_any_page(session["host"], session["port"], timeout=30)
    except Exception as exc:
        fail("CDP 连接失败: %s" % exc, code=EXIT_ENV, event="env_unavailable")
    backend = type("Backend", (), {"query": staticmethod(lambda q: _runtime_query(conn, q))})()
    checks, passed = evaluate_page(backend, manifest)
    conn.close()

    report = {"manifest": os.path.abspath(manifest_path),
              "passed": passed, "checks": checks}
    with open(report_out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    emit_event("eval_done", passed=passed, report=os.path.abspath(report_out),
               summary={c["name"]: c["pass"] for c in checks})
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="CDP 交互/内容自动验收")
    ap.add_argument("--session", required=True, help="launch 阶段输出的会话 JSON")
    ap.add_argument("--manifest", required=True, help="seed 阶段输出的真值清单")
    ap.add_argument("--report-out", required=True, help="验收报告 JSON")
    args = ap.parse_args(argv)
    run(args.session, args.manifest, args.report_out)


if __name__ == "__main__":
    main()
