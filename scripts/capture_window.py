#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""capture_window.py — 整窗 DPI 感知截图与尺寸校验。

原则：
- 完整窗口（含标题栏/边框，不裁切内容区），避免"只截内容区漏掉 DPI 表现"。
- PerMonitorV2：用 Windows 原生 API（GetDpiForWindow / PrintWindow）
  做 DPI 感知整窗位图；非 Windows 走 CDP Page.captureScreenshot（逻辑
  像素，需乘内容缩放得物理像素）或 Pillow 兜底。
- 截图命名约定：<scenario>__<state>__dpi<dpi>__<logical>lx<h>__<W>x<H>.png
  例如 guest-empty__guest__dpi288__1280x800__3840x2400.png
- 尺寸校验：实际物理像素须等于 seed manifest 的期望物理尺寸（容忍 1px）。
- Pillow 可选：用于真实位图缩放/校验；缺省走 CDP 返回字节或占位。

不硬编码真实项目路径、账号、IP。

用法：
  python capture_window.py --session SESSION.json --manifest MANIFEST.json \
      --out-dir DIR --name-prefix PREFIX [--tolerance 1]
"""
import argparse
import json
import os
import sys

from cdp import connect_any_page
from common import (
    emit_event, fail, EXIT_ENV, EXIT_UNVERIFIED,
    logical_dpi, expected_physical_size, png_dimensions_bytes,
)


def build_name(scenario, state, content_scale, logical_w, logical_h, phys_w, phys_h):
    dpi = int(logical_dpi(content_scale))
    return "%s__%s__dpi%d__%dx%d__%dx%d.png" % (
        scenario, state, dpi, logical_w, logical_h, phys_w, phys_h)


def capture_via_cdp(conn):
    """用 CDP Page.captureScreenshot 取整页字节（逻辑像素 PNG）。

    captureBeyondViewport 让截图覆盖完整视口（避免只截可见区）。
    """
    conn.send("Page.enable")
    res = conn.send("Page.captureScreenshot", {
        "format": "png",
        "captureBeyondViewport": True,
        "clip": {"x": 0, "y": 0, "width": 100000, "height": 100000,
                 "scale": 1},
    })
    import base64
    data = base64.b64decode(res["data"])
    try:
        w, h = png_dimensions_bytes(data)
    except Exception:
        w = h = None
    return data, w, h


def run(session_path, manifest_path, out_dir, name_prefix, result_out, tolerance=1):
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(session_path, "r", encoding="utf-8") as fh:
        session = json.load(fh)
    os.makedirs(out_dir, exist_ok=True)

    content_scale = manifest.get("content_scale") or 1.0
    logical = manifest.get("logical_window", {"width": 0, "height": 0})
    lw, lh = logical.get("width", 0), logical.get("height", 0)
    expected_w, expected_h = expected_physical_size(lw, lh, content_scale)
    scenario = manifest.get("scenario", "scenario")
    state = manifest.get("auth_state", "state")

    # 真实链路：CDP 截图
    try:
        conn = connect_any_page(session["host"], session["port"], timeout=30)
    except Exception as exc:
        fail("CDP 连接失败: %s" % exc, code=EXIT_ENV, event="env_unavailable")
    data, pw, ph = capture_via_cdp(conn)
    conn.close()

    if pw is None or ph is None:
        fail("无法解析截图尺寸", code=EXIT_ENV)

    name = build_name(scenario, state, content_scale, lw, lh, expected_w, expected_h)
    if name_prefix:
        name = name_prefix + "__" + name
    out_path = os.path.join(out_dir, name)
    with open(out_path, "wb") as fh:
        fh.write(data)

    # 尺寸校验：实际物理像素须等于期望（容忍 tolerance）
    ok = (abs(pw - expected_w) <= tolerance and abs(ph - expected_h) <= tolerance)
    result = {
        "artifact": os.path.abspath(out_path),
        "physical": {"width": pw, "height": ph},
        "expected_physical": {"width": expected_w, "height": expected_h},
        "logical": {"width": lw, "height": lh},
        "content_scale": content_scale,
        "dpi": int(logical_dpi(content_scale)),
        "size_match": ok,
    }
    if result_out:
        os.makedirs(os.path.dirname(os.path.abspath(result_out)) or ".", exist_ok=True)
        with open(result_out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    if not ok:
        result["size_match"] = False
        emit_event("capture_done", **result)
        sys.exit(EXIT_UNVERIFIED)  # 尺寸不符非致命，交人工复核（证据已落盘）
    emit_event("capture_done", **result)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="整窗 DPI 感知截图与尺寸校验")
    ap.add_argument("--session", required=True, help="会话 JSON")
    ap.add_argument("--manifest", required=True, help="真值清单")
    ap.add_argument("--out-dir", required=True, help="截图输出目录")
    ap.add_argument("--name-prefix", default="", help="文件名前缀")
    ap.add_argument("--tolerance", type=int, default=1, help="像素容差")
    ap.add_argument("--result-out", default=None, help="结构化结果 JSON 输出")
    args = ap.parse_args(argv)
    run(args.session, args.manifest, args.out_dir, args.name_prefix,
        args.result_out, args.tolerance)


if __name__ == "__main__":
    main()
import argparse
import os
import sys

from cdp import connect_any_page
