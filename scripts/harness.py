#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""harness.py — 一键编排：seed → launch → eval → capture → verify。

把分散的 CLI 串成一次可复跑的验收。每个子阶段都是独立可执行的脚本，
harness 只是按顺序调用并透传状态文件，便于单独复跑某一步。

不触碰真实账号、不硬编码项目路径。被测程序路径必须显式传入。

用法：
  python harness.py --program EXE --url URL --scenario guest-with-tasks \
      --out-dir RUN --content-scale 3.0 [--keep]
"""
import argparse
import json
import os
import subprocess
import sys

from common import emit_event, EXIT_ENV, EXIT_INPUT, EXIT_UNVERIFIED, EXIT_OK

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = HERE


def _run(script, args, check=True):
    cmd = [sys.executable, os.path.join(SCRIPTS, script)] + args
    emit_event("step", script=script, args=args)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    # 转发子进程每行输出（事件流保持可解析）
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if check and proc.returncode != 0:
        raise RuntimeError("%s 失败 rc=%d" % (script, proc.returncode))
    return proc.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description="一键视觉验收编排")
    ap.add_argument("--program", required=True, help="被测程序绝对路径")
    ap.add_argument("--url", default="about:blank", help="初始 URL")
    ap.add_argument("--scenario", default="guest-empty",
                    help="seed 场景名")
    ap.add_argument("--out-dir", required=True, help="本次运行输出目录")
    ap.add_argument("--content-scale", type=float, default=None,
                    help="期望内容缩放(如 3.0)")
    ap.add_argument("--port", type=int, default=9222, help="CDP 端口")
    ap.add_argument("--headless", action="store_true", help="无头启动")
    ap.add_argument("--keep", action="store_true", help="保留 CDP 会话(不自动关闭)")
    args = ap.parse_args(argv)

    if not os.path.exists(args.program):
        emit_event("error", error="被测程序不存在: %s" % args.program)
        sys.exit(EXIT_INPUT)

    out = os.path.abspath(args.out_dir)
    os.makedirs(out, exist_ok=True)
    data_dir = os.path.join(out, "mock_data")
    user_data_dir = os.path.join(out, "user_data")
    manifest = os.path.join(out, "manifest.json")
    session = os.path.join(out, "session.json")
    eval_report = os.path.join(out, "eval_report.json")
    capture = os.path.join(out, "capture.json")
    artifact_manifest = os.path.join(out, "artifact_manifest.json")
    shot_dir = os.path.join(out, "shots")
    os.makedirs(shot_dir, exist_ok=True)

    # 1) seed
    _run("seed.py", ["--data-dir", data_dir, "--manifest-out", manifest,
                     "--scenario", args.scenario])

    # 2) launch
    launch_args = ["--program", args.program, "--user-data-dir", user_data_dir,
                   "--port", str(args.port), "--url", args.url,
                   "--data-dir", data_dir, "--session-out", session]
    if args.content_scale is not None:
        launch_args += ["--content-scale", str(args.content_scale)]
    if args.headless:
        launch_args.append("--headless")
    _run("launch_cdp.py", launch_args)

    # 3) eval
    _run("cdp_eval.py", ["--session", session, "--manifest", manifest,
                         "--report-out", eval_report])

    # 4) capture
    cap_rc = _run("capture_window.py", ["--session", session,
                                       "--manifest", manifest,
                                       "--out-dir", shot_dir,
                                       "--result-out", capture,
                                       "--tolerance", "1"],
                  check=False)

    # 5) verify（capture 尺寸不符时仍校验其余证据）
    ver_rc = _run("verify_artifacts.py",
                  ["--manifest", manifest, "--eval-report", eval_report,
                   "--capture", capture,
                   "--artifact-manifest-out", artifact_manifest],
                  check=False)

    # capture_window 把结果写到 out_dir/capture.json？这里用约定路径修正：
    # capture_window 仅写 PNG；verify 需要 capture 结果 JSON，由 harness 组装。
    emit_event("harness_done", eval_rc=0, capture_rc=cap_rc, verify_rc=ver_rc,
               artifact_manifest=artifact_manifest)
    if cap_rc != 0 or ver_rc != 0:
        sys.exit(EXIT_UNVERIFIED)
    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
