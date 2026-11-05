#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seed.py — 准备隔离 mock 数据与派生真值清单（ground-truth manifest）。

职责：把"被测程序在游客态/演示态应展示什么"沉淀成可复跑的 JSON 真值，
落到一个独立数据目录（不污染真实安装目录、不触碰真实账号/任务）。

纯 Python 标准库；不硬编码任何真实项目路径、手机号、IP、session。

用法：
  python seed.py --data-dir DIR --manifest-out MANIFEST.json [--scenario NAME]
"""
import argparse
import json
import os
import sys

from common import emit_event, EXIT_INPUT

# 内置的场景库。每个场景描述"游客态/演示态"应展示的确定性内容，
# 与具体被测程序解耦；examples/ 里演示如何对接 TVG 真实例子。
SCENARIOS = {
    "guest-empty": {
        "label": "游客空态",
        "auth_state": "guest",
        "logical_window": {"width": 1280, "height": 800},
        "content_scale": 1.0,
        "expected": {
            "guest_banner_present": True,
            "login_prompt_present": True,
            "task_list": [],
            "non_interactive_error_bar_hidden": True,
            "title_text": "示例演示程序",
        },
    },
    "guest-with-tasks": {
        "label": "游客带 mock 任务",
        "auth_state": "guest",
        "logical_window": {"width": 1280, "height": 800},
        "content_scale": 3.0,
        "expected": {
            "guest_banner_present": True,
            "login_prompt_present": False,
            "task_list": [
                {"id": "task-001", "title": "示例任务一", "progress": 0},
                {"id": "task-002", "title": "示例任务二", "progress": 50},
            ],
            "non_interactive_error_bar_hidden": True,
            "title_text": "示例演示程序",
        },
    },
}


def prepare(data_dir, scenario_name, manifest_out):
    if scenario_name not in SCENARIOS:
        emit_event("error", error="未知 scenario: %s" % scenario_name,
                   available=list(SCENARIOS.keys()))
        sys.exit(EXIT_INPUT)
    os.makedirs(data_dir, exist_ok=True)
    scenario = SCENARIOS[scenario_name]

    # 写入 mock 数据（与被测程序约定的文件名，仅示例约定，非真实 app）
    mock_state = {
        "scenario": scenario_name,
        "auth_state": scenario["auth_state"],
        "tasks": scenario["expected"].get("task_list", []),
        "error_bar": {"message": "", "visible": False},
    }
    state_path = os.path.join(data_dir, "mock_state.json")
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(mock_state, fh, ensure_ascii=False, indent=2)

    manifest = {
        "scenario": scenario_name,
        "label": scenario["label"],
        "auth_state": scenario["auth_state"],
        "logical_window": scenario["logical_window"],
        "content_scale": scenario["content_scale"],
        "expected": scenario["expected"],
        "data_dir": os.path.abspath(data_dir),
        "mock_state_file": os.path.abspath(state_path),
    }
    with open(manifest_out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    emit_event("seeded", scenario=scenario_name, data_dir=manifest["data_dir"],
               manifest=os.path.abspath(manifest_out),
               mock_state_file=manifest["mock_state_file"])
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description="准备隔离 mock 数据与真值清单")
    ap.add_argument("--data-dir", required=True, help="独立 mock 数据目录")
    ap.add_argument("--manifest-out", required=True, help="输出的真值清单 JSON")
    ap.add_argument("--scenario", default="guest-empty",
                    choices=list(SCENARIOS.keys()), help="场景名")
    args = ap.parse_args(argv)
    prepare(args.data_dir, args.scenario, args.manifest_out)


if __name__ == "__main__":
    main()
