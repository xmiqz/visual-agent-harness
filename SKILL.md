---
name: visual-agent-harness
description: 用真实程序 + 隔离 mock 数据 + CDP 驱动 + DPI 感知整窗截图 + 视觉/交互自动验收，对 Windows 桌面/WebView2/浏览器前端做可复跑的可视化验收，通用不限于某个具体项目
---

# visual-agent-harness

一套**通用**方法（不只是 TVG）：把"前端界面是否真的按规范显示/可交互"
变成可复跑、可核验的证据。对象是被测的**真实程序**（不是截图里的假 UI），
但用隔离 mock 数据驱动它在游客/演示态展示确定性内容，再用 CDP 驱动页面
做交互验收、用 DPI 感知整窗截图做视觉验收，最后汇总成证据 manifest。

## 0. 第一原则（每次调用都适用）

1. **验证真实程序，不是假 UI**。你要的是被测程序在游客/演示态真实渲染
   出来的整窗截图，而非手绘或 AI 生成的界面图。
2. **数据隔离**。永远用独立的 `--user-data-dir` 与 `--data-dir`，绝不
   指向真实安装目录或真实账号数据；被测程序通过环境变量读取 mock 数据。
3. **DPI 感知整窗截图**。必须用 PerMonitorV2 下的完整窗口截图（含标题栏
   /边框），并按 `content_scale` 校验物理像素尺寸；只截内容区会漏掉
   高缩放下标题栏/边框的渲染差异。
4. **截图不得被编辑遮盖**。产出的是验收证据，任何编辑（裁剪、贴图、调色）
   都必须在报告里声明，不能在未声明情况下改动原始截图。
5. **可复跑证据**。每次运行都落盘 `manifest.json / eval_report.json /
   capture.json / artifact_manifest.json / shots/*.png`，结论可追溯。
6. **人工最终验收**。自动验收只做"确定性断言"；证据存在但某项未达阈值
   时交人工复核（rc=2），**绝不伪造通过结论**。
7. **零三方依赖**。脚本只用 Python 标准库（截图 Pillow 可选），不联网
   拉包、不碰真实账号。

## 1. 适用场景（触发）

- 前端高 DPI（如 300%）下整窗布局/字号/边框是否正确的回归验收。
- 游客态/演示态 vs 登录态的内容差异核对（如隐藏非交互错误条、横幅）。
- 任务列表/进度等 DOM 内容与真值清单的一致性验收。
- 多显示器、PerMonitorV2 下的窗口缩放/位置正确性核查。
- WebView2 宿主应用或任意 Chromium 内核桌面前端的"真实程序截图"取证。

## 2. 工作模型

```
真实被测程序(exe) ── --user-data-dir(--隔离) ── --remote-debugging-port(CDP)
        │
        ├─ seed       准备 mock 数据 + 真值 manifest
        ├─ launch_cdp 启动程序并暴露 CDP 端点
        ├─ cdp_eval   驱动页面做交互/内容断言(Runtime.evaluate)
        ├─ capture    整窗 DPI 感知截图 + 尺寸校验
        └─ verify     汇总证据 + 结论(verified/unverified)
```

调用方智能体（你）负责任务书/真值、参数、人工终验；harness 只做可复跑
的确定性采集与断言。证据齐且自动通过 → verified(rc0)；证据存在但某项
未达阈值 → unverified(rc2)，你立即人工复核证据；环境/输入问题 → rc3/4。

## 3. 命令速查

| 命令 | 用途 |
|------|------|
| seed.py | 准备隔离 mock 数据 + 真值清单 |
| launch_cdp.py | 启动被测程序并暴露 CDP 端点（隔离 user-data-dir） |
| cdp_eval.py | CDP 驱动页面做交互/内容自动验收 |
| capture_window.py | 整窗 DPI 感知截图 + 物理尺寸校验 + 命名约定 |
| verify_artifacts.py | 汇总证据 manifest + 结论 |
| harness.py | 一键编排以上五步 |
| common.py / cdp.py | 共享工具（事件/退出码/DPI 换算/最小 CDP 客户端） |

通用参数：`--program`（被测 exe，必显式传，脚本不内置路径）、
`--user-data-dir`（隔离）、`--data-dir`（mock，隔离）、`--content-scale`
（如 `3.0`）、`--port`（CDP，默认 9222）。

## 4. 退出码语义

| rc | 含义 | 你要做什么 |
|----|------|-----------|
| 0 | verified | 证据齐且自动验收通过，进入人工终验 |
| 2 | unverified | 证据存在但某项未达阈值（尺寸偏差/交互项不符/命名不符）→ 立即人工复核截图与 manifest，不要当失败重跑 |
| 3 | env_unavailable | 程序不在 / CDP 连不上 / 截图失败 → 修正路径与端口后重跑 |
| 4 | input | 参数非法（尺寸/缩放/路径）→ 修正参数重跑 |

## 5. 命名约定（截图）

```
<prefix>__<scenario>__<state>__dpi<dpi>__<逻辑W>x<逻辑H>__<物理W>x<物理H>.png
```
例：`tvg__guest-with-tasks__guest__dpi288__1280x800__3840x2400.png`

## 6. 隔离与隐私红线

- 不内置任何真实程序路径、手机号、IP、账号、session、个人路径。
- `--program` / `--user-data-dir` / `--data-dir` 必须由调用方显式提供，
  且后两者必须是运行内独立目录。
- 被测程序读 `VAH_MOCK_DATA_DIR` / `VAH_CONTENT_SCALE` 进入演示态（约定
  名，详见 docs/usage.md）。仓库自检：`grep -rEi '1[3-9][0-9]{8,}|[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' .` 不应命中真实敏感串。

## 7. 自检与排障

- 零依赖冒烟（内置假 CDP/fake 窗口，不联网）：
  `python tests/smoke_test.py`，应全过。
- 改任何 scripts 后必须重跑冒烟；真实链路只用演示/游客态 + 占位 URL，
  不依赖真实账号联网。
- 报告结论须列脚本路径 + 命令 + 结果片段；不能验证的部分停下来报告，
  不声称通过（见 docs/failure_modes.md）。

## 目录

scripts/ 各阶段 CLI + 共享模块；docs/ 协议/用法/失败模式；
examples/ 真实例子（TVG 游客态 + DPI 300%）；tests/ 零依赖自测。
