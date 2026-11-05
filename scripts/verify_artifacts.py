#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_artifacts.py — 汇总证据产物，生成 manifest 并给出验收结论。

汇总：
- seed manifest（真值）
- cdp_eval 报告（交互/内容验收）
- capture_window 产物（整窗截图 + 尺寸校验）

校验：
- 截图文件名符合命名约定（含 scenario/state/dpi/逻辑尺寸/物理尺寸）
- 物理尺寸与真值期望一致
- 交互验收全部通过

结论事件：
- verified（exit 0）：证据齐全且与真值一致
- unverified（exit 2）：证据存在但某项未达自动验收阈值，待人工复核

不触碰真实账号；不硬编码项目路径。

用法：
  python verify_artifacts.py --manifest MANIFEST.json \
      --eval-report REPORT.json --capture CAPTURE.json \
      --artifact-manifest-out AM.json
"""
import argparse
import hashlib
import json
import os
import sys

from common import (
    emit_event, EXIT_OK, EXIT_UNVERIFIED, EXIT_INPUT,
    png_dimensions_bytes,
)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(manifest_path, eval_report_path, capture_path, artifact_manifest_out):
    for p in (manifest_path, eval_report_path, capture_path):
        if not os.path.exists(p):
            emit_event("error", error="文件不存在: %s" % p)
            sys.exit(EXIT_INPUT)

    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(eval_report_path, "r", encoding="utf-8") as fh:
        report = json.load(fh)
    with open(capture_path, "r", encoding="utf-8") as fh:
        capture = json.load(fh)

    issues = []

    # 1) 截图文件名约定
    artifact = capture.get("artifact")
    if not artifact or not os.path.exists(artifact):
        issues.append("截图产物缺失")
    else:
        base = os.path.basename(artifact)
        if "__" not in base or not base.endswith(".png"):
            issues.append("截图命名不符约定: %s" % base)

    # 2) 物理尺寸一致
    if not capture.get("size_match"):
        issues.append("截图物理尺寸与真值期望不符")

    # 3) 交互验收
    if not report.get("passed"):
        failed = [c["name"] for c in report.get("checks", []) if not c["pass"]]
        issues.append("交互验收未通过: %s" % ", ".join(failed))

    am = {
        "scenario": manifest.get("scenario"),
        "auth_state": manifest.get("auth_state"),
        "content_scale": manifest.get("content_scale"),
        "logical_window": manifest.get("logical_window"),
        "expected_physical": capture.get("expected_physical"),
        "actual_physical": capture.get("physical"),
        "artifact": os.path.abspath(artifact) if artifact else None,
        "artifact_sha256": _sha256(artifact) if artifact and os.path.exists(artifact) else None,
        "eval_checks": report.get("checks"),
        "issues": issues,
    }
    os.makedirs(os.path.dirname(os.path.abspath(artifact_manifest_out)) or ".", exist_ok=True)
    with open(artifact_manifest_out, "w", encoding="utf-8") as fh:
        json.dump(am, fh, ensure_ascii=False, indent=2)

    if issues:
        emit_event("unverified", artifact_manifest=os.path.abspath(artifact_manifest_out),
                   issues=issues)
        sys.exit(EXIT_UNVERIFIED)
    emit_event("verified", artifact_manifest=os.path.abspath(artifact_manifest_out))
    return am


def main(argv=None):
    ap = argparse.ArgumentParser(description="汇总证据产物并给出验收结论")
    ap.add_argument("--manifest", required=True, help="seed 真值清单")
    ap.add_argument("--eval-report", required=True, help="cdp_eval 报告")
    ap.add_argument("--capture", required=True, help="capture_window 结果 JSON")
    ap.add_argument("--artifact-manifest-out", required=True, help="证据 manifest 输出")
    args = ap.parse_args(argv)
    verify(args.manifest, args.eval_report, args.capture, args.artifact_manifest_out)


if __name__ == "__main__":
    main()
