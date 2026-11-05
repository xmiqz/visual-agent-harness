#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smoke_test.py — visual-agent-harness 零依赖全链路自测（不联网）。

覆盖：
 1. DPI / 缩放换算（logical_dpi / 物理尺寸 / 100%/200%/300%）
 2. 零依赖 PNG 编解码往返（尺寸正确）
 3. seed 生成隔离 mock 数据 + 真值 manifest
 4. cdp_eval 通过 fake 后端断言 DOM 内容（游客态/任务列表/错误条隐藏）
 5. capture_window 命名约定 + 物理尺寸校验（用 fake CDP 返回 PNG 字节）
 6. verify_artifacts 汇总证据 manifest + 结论（verified / unverified）
 7. 整链路：fake CDP 服务跑 seed→eval→capture→verify

直接运行：python tests/smoke_test.py；任一断言失败退出码 1。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
PY = sys.executable

sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from common import (  # noqa: E402
    logical_dpi, physical_dpi, expected_physical_size,
    logical_to_physical, encode_png, decode_png, png_dimensions_bytes,
)
import fake_cdp_server  # noqa: E402


def test_dpi_math():
    assert logical_dpi(1.0) == 96, "100% 应为 96 DPI"
    assert logical_dpi(2.0) == 192, "200% 应为 192 DPI"
    assert logical_dpi(3.0) == 288, "300% 应为 288 DPI"
    assert expected_physical_size(1280, 800, 1.0) == (1280, 800)
    assert expected_physical_size(1280, 800, 3.0) == (3840, 2400), "300% 物理尺寸"
    assert expected_physical_size(1280, 800, 2.0) == (2560, 1600)
    assert logical_to_physical(100, 1.25) == 125, "125% 缩放"
    assert physical_dpi(3.0) == 288.0
    print("[ok] DPI / 缩放换算")


def test_png_roundtrip():
    w, h = 4, 3
    pixels = bytes([10, 20, 30]) * (w * h)
    png = encode_png(w, h, pixels)
    dw, dh, mode, out = decode_png(png)
    assert (dw, dh, mode) == (w, h, "RGB"), "PNG 尺寸/模式"
    assert out == pixels, "PNG 像素往返一致"
    assert png_dimensions_bytes(png) == (w, h), "字节读取尺寸"
    print("[ok] 零依赖 PNG 编解码往返")


def test_seed(tmp):
    data_dir = os.path.join(tmp, "mock")
    manifest = os.path.join(tmp, "manifest.json")
    r = subprocess.run(
        [PY, os.path.join(SCRIPTS, "seed.py"), "--data-dir", data_dir,
         "--manifest-out", manifest, "--scenario", "guest-with-tasks"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, "seed 应成功: " + r.stderr
    with open(manifest, "r", encoding="utf-8") as fh:
        m = json.load(fh)
    assert m["scenario"] == "guest-with-tasks"
    assert m["content_scale"] == 3.0, "DPI 300%"
    assert m["expected"]["non_interactive_error_bar_hidden"] is True
    assert len(m["expected"]["task_list"]) == 2
    assert os.path.exists(os.path.join(data_dir, "mock_state.json"))
    print("[ok] seed 隔离 mock 数据 + 真值清单")
    return manifest


def test_eval_via_fake_backend(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as fh:
        m = json.load(fh)
    backend = fake_cdp_server.FakePageBackend(m)
    from cdp_eval import evaluate_page
    checks, passed = evaluate_page(backend, m)
    assert passed is True, "fake 后端应与真值一致: " + str(checks)
    names = {c["name"] for c in checks}
    assert {"title_text", "guest_banner_present", "login_prompt_present",
            "non_interactive_error_bar_hidden", "task_list"} <= names
    print("[ok] cdp_eval 交互/内容断言（fake 后端）")


def test_eval_mismatch(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as fh:
        m = json.load(fh)
    backend = fake_cdp_server.FakePageBackend(m)
    # 故意篡改真值，验收应失败
    bad = dict(m)
    bad["expected"] = dict(m["expected"])
    bad["expected"]["title_text"] = "错误标题"
    from cdp_eval import evaluate_page
    checks, passed = evaluate_page(backend, bad)
    assert passed is False, "真值不符应判未通过"
    print("[ok] cdp_eval 真值不符判未通过")


def test_capture_and_verify(tmp, manifest_path):
    srv, fake, ws = fake_cdp_server.start(
        json.load(open(manifest_path, encoding="utf-8")), port=9223)
    try:
        session = os.path.join(tmp, "session.json")
        with open(session, "w", encoding="utf-8") as fh:
            json.dump({"host": "127.0.0.1", "port": 9223, "target_id": "fake-page-1"},
                      fh)
        shot_dir = os.path.join(tmp, "shots")
        capture = os.path.join(tmp, "capture.json")
        r = subprocess.run(
            [PY, os.path.join(SCRIPTS, "capture_window.py"),
             "--session", session, "--manifest", manifest_path,
             "--out-dir", shot_dir, "--result-out", capture, "--tolerance", "1"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0, "capture 应成功: " + r.stderr
        with open(capture, "r", encoding="utf-8") as fh:
            cap = json.load(fh)
        # 命名约定
        base = os.path.basename(cap["artifact"])
        assert "dpi288" in base and "1280x800" in base and "3840x2400" in base, base
        assert cap["size_match"] is True
        # verify
        report = os.path.join(tmp, "eval_report.json")
        with open(report, "w", encoding="utf-8") as fh:
            json.dump({"passed": True, "checks": []}, fh)
        am = os.path.join(tmp, "artifact_manifest.json")
        r2 = subprocess.run(
            [PY, os.path.join(SCRIPTS, "verify_artifacts.py"),
             "--manifest", manifest_path, "--eval-report", report,
             "--capture", capture, "--artifact-manifest-out", am],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r2.returncode == 0, "verify 应 verified: " + r2.stderr
        with open(am, "r", encoding="utf-8") as fh:
            amj = json.load(fh)
        assert amj["artifact_sha256"], "应记录截图 sha256"
        assert amj["issues"] == []
        print("[ok] capture 命名+尺寸校验 + verify 汇总证据")
    finally:
        srv.shutdown()


def test_verify_unverified(tmp, manifest_path):
    # 制造尺寸不符的 capture，verify 应 unverified(rc=2)
    cap = {"artifact": os.path.join(tmp, "x.png"),
           "physical": {"width": 1, "height": 1},
           "expected_physical": {"width": 3840, "height": 2400},
           "size_match": False}
    cap_path = os.path.join(tmp, "cap_bad.json")
    with open(cap_path, "w", encoding="utf-8") as fh:
        json.dump(cap, fh)
    with open(os.path.join(tmp, "x.png"), "wb") as fh:
        fh.write(b"")
    report = os.path.join(tmp, "eval_report.json")
    with open(report, "w", encoding="utf-8") as fh:
        json.dump({"passed": True, "checks": []}, fh)
    am = os.path.join(tmp, "am.json")
    r = subprocess.run(
        [PY, os.path.join(SCRIPTS, "verify_artifacts.py"),
         "--manifest", manifest_path, "--eval-report", report,
         "--capture", cap_path, "--artifact-manifest-out", am],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 2, "尺寸不符应 unverified(rc=2): " + r.stdout
    print("[ok] verify 尺寸不符 → unverified(rc=2)")


def test_full_chain(tmp):
    manifest = test_seed(tmp)
    test_eval_via_fake_backend(manifest)
    test_capture_and_verify(tmp, manifest)
    print("[ok] 整链路 seed→eval→capture→verify（fake CDP，不联网）")


def main():
    tmp = tempfile.mkdtemp(prefix="vah-smoke-")
    try:
        test_dpi_math()
        test_png_roundtrip()
        test_seed(tmp)
        manifest = os.path.join(tmp, "manifest.json")
        test_eval_via_fake_backend(manifest)
        test_eval_mismatch(manifest)
        test_capture_and_verify(tmp, manifest)
        test_verify_unverified(tmp, manifest)
        test_full_chain(tmp)
        print("\nALL SMOKE TESTS PASSED")
        return 0
    except AssertionError as exc:
        print("\nSMOKE FAIL: %s" % exc)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
