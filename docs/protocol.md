# 协议说明（protocol）

visual-agent-harness 是一套"真实程序 + 隔离 mock 数据 + CDP 驱动 + 整窗
DPI 感知截图 + 视觉/交互自动验收"的可复用方法。本文件定义其内部协议。

## 阶段与产物

```
seed ──▶ launch_cdp ──▶ cdp_eval ──▶ capture_window ──▶ verify_artifacts
 │            │              │               │                │
manifest  session        eval_report      shot + capture    artifact_manifest
```

每一步都是独立 CLI，状态通过 JSON 文件在步骤间透传；harness.py 只是按
顺序调用它们，便于单独复跑任意一步。

## 事件流约定

- 所有脚本向 stdout 打印**单行 JSON 事件**（`common.emit_event`）。
- 调用方智能体只解析末行判断终态；中间事件是过程观测，不作为分支依据。
- 退出码语义（与 SKILL.md 一致）：

| rc | 含义 | 调用方该做什么 |
|----|------|----------------|
| 0 | verified / 完成 | 证据齐且自动验收通过，可进入人工终验 |
| 2 | unverified | 证据存在但某项未达自动阈值（如尺寸差 1px、交互项不符），**立即人工复核**证据，不要当作失败重跑 |
| 3 | env_unavailable | 被测程序不在 / CDP 连不上 / 截图失败；检查路径与端口后重跑 |
| 4 | input | 参数非法（尺寸/缩放/路径）；修正参数后重跑 |

## 命名约定（截图文件名）

```
<name-prefix>__<scenario>__<state>__dpi<dpi>__<逻辑W>x<逻辑H>__<物理W>x<物理H>.png
```

例：`tvg__guest-with-tasks__guest__dpi288__1280x800__3840x2400.png`

- `dpi`：系统报告的逻辑 DPI（96 基准 × 内容缩放，PerMonitorV2 真实值）。
- `物理W×物理H`：期望的物理像素（= 逻辑尺寸 × 内容缩放），截图实际尺寸
  须与之匹配（容忍 1px）。

## 真实值（ground-truth）约定

- seed 阶段把"被测程序在游客/演示态应展示什么"沉淀为 `manifest.json`，
  由调用方在验收前确认（真值不是脚本凭空生成，而是人工/既有规范导出）。
- cdp_eval 与 verify 的所有断言都来自 manifest，不臆造期望。

## 隔离约定

- `--user-data-dir` 指向运行目录内的独立目录，绝不触碰真实安装目录/账号。
- `--data-dir`（mock 数据）同样运行内独立，真实程序通过环境变量
  `VAH_MOCK_DATA_DIR` / `VAH_CONTENT_SCALE` 读取（约定见 usage.md）。
- 仓库内不含任何真实手机号、IP、账号、session、个人路径。

## CDP 端点

- 被测程序以 `--remote-debugging-port` 暴露；harness 通过 HTTP `/json`
  枚举目标、取 WebSocket 端点。
- 真实驱动走 WebSocket（标准库最小实现）；自测由 fake CDP 桩替代，不联网。
