# 用法（usage）

## 前置条件

1. Python 3.9+（纯标准库，零三方依赖；Windows 主路径）。
2. 一个 Chromium 内核的被测程序（WebView2 宿主 exe 或浏览器），支持
   `--remote-debugging-port` 与 `--user-data-dir`。
3. 被测程序支持"演示/游客态 + 隔离数据"入口：读取环境变量
   `VAH_MOCK_DATA_DIR`（隔离 mock 数据目录）与 `VAH_CONTENT_SCALE`
   （期望内容缩放，如 `3.0`）。约定名可改，但必须在被测侧实现等价注入。

> 真实截图优先 Pillow（缩放/校验），但非必需：缺省走 CDP 返回字节。

## 逐步用法

```bash
# 0) seed：准备隔离 mock 数据 + 真值清单
python scripts/seed.py --data-dir run/mock_data \
  --manifest-out run/manifest.json --scenario guest-with-tasks

# 1) launch：启动被测程序并暴露 CDP
python scripts/launch_cdp.py --program "C:/path/to/Host.exe" \
  --user-data-dir run/user_data --port 9222 \
  --url "https://example.invalid/demo" \
  --data-dir run/mock_data --content-scale 3.0 \
  --session-out run/session.json

# 2) eval：CDP 驱动页面做交互/内容验收
python scripts/cdp_eval.py --session run/session.json \
  --manifest run/manifest.json --report-out run/eval_report.json

# 3) capture：整窗 DPI 感知截图 + 尺寸校验
python scripts/capture_window.py --session run/session.json \
  --manifest run/manifest.json --out-dir run/shots \
  --result-out run/capture.json --tolerance 1

# 4) verify：汇总证据 + 结论
python scripts/verify_artifacts.py --manifest run/manifest.json \
  --eval-report run/eval_report.json --capture run/capture.json \
  --artifact-manifest-out run/artifact_manifest.json
```

## 一键编排

```bash
python scripts/harness.py --program "C:/path/to/Host.exe" \
  --url "https://example.invalid/demo" --scenario guest-with-tasks \
  --out-dir run --content-scale 3.0
```

harness 在 `out-dir` 内生成 `manifest.json / session.json / eval_report.json
/ capture.json / artifact_manifest.json / shots/*.png / mock_data/ `。

## 环境变量约定（被测程序侧）

| 变量 | 含义 |
|------|------|
| `VAH_MOCK_DATA_DIR` | 隔离 mock 数据目录绝对路径 |
| `VAH_CONTENT_SCALE` | 期望内容缩放（字符串，如 `1.0`/`3.0`） |

被测程序在演示态应：从该目录读取 `mock_state.json`、按 `content_scale`
设置根容器/窗口缩放、隐藏非交互错误条、展示游客态横幅与 mock 任务。

## 名称 / 数据隔离红线

- 不允许把真实安装目录或真实账号数据目录作为 `--user-data-dir` / `--data-dir`。
- 不允许在脚本或 manifest 中写入真实手机号、IP、账号、session、个人路径。
- `--program` 必须由调用方显式传入，脚本不内置任何程序路径。
