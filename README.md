# visual-agent-harness

一套**通用**方法：用真实程序 + 隔离 mock 数据 + CDP 驱动 + DPI 感知整窗
截图 + 视觉/交互自动验收，对 Windows 桌面 / WebView2 / 浏览器前端做可复跑
的可视化验收。**不限于 TVG**，任何 Chromium 内核的桌面前端都能用。

- 验证的是**真实被测程序**在游客/演示态的真实渲染（不是 AI 生成的假 UI）；
- 数据**隔离**：独立 `--user-data-dir` / `--data-dir`，不碰真实账号；
- **PerMonitorV2 整窗截图**：含标题栏/边框，按 `content_scale` 校验物理
  像素尺寸（如 300% → 逻辑 1280×800 应得 3840×2400）；
- 证据可复跑、可溯源；自动验收未通过的证据**交人工复核**，不伪造结论；
- 纯 Python 标准库（截图 Pillow 可选），零三方依赖，不联网拉包。

## 工作模型

```
真实被测程序(exe) ── 隔离 user-data-dir ── --remote-debugging-port(CDP)
   │
   ├─ seed        准备 mock 数据 + 真值 manifest
   ├─ launch_cdp  启动程序并暴露 CDP 端点
   ├─ cdp_eval    CDP 驱动页面做交互/内容断言
   ├─ capture     整窗 DPI 感知截图 + 尺寸校验
   └─ verify      汇总证据 + 结论(verified / unverified)
```

调用方智能体负责任务书/真值、参数与人工终验；harness 只做确定性采集与
断言。退出码：`0=verified`、`2=unverified(交人工)`、`3=env_unavailable`、
`4=input`。末行非 0 必为 `unverified`/`error` 事件。

## 前置条件

1. Python 3.9+（直接用任意 Python 运行时即可，无需 pip install）。
2. 一个 Chromium 内核被测程序（WebView2 宿主 exe 或浏览器），支持
   `--remote-debugging-port` 与 `--user-data-dir`，并实现演示态注入
   （读 `VAH_MOCK_DATA_DIR` / `VAH_CONTENT_SCALE`，见 docs/usage.md）。

## 快速开始

```bash
# 一键编排：seed → launch → eval → capture → verify
python scripts/harness.py \
  --program "C:/path/to/Host.exe" \
  --url "https://example.invalid/demo" \
  --scenario guest-with-tasks \
  --out-dir run --content-scale 3.0
```

`out-dir` 内生成 `manifest.json / session.json / eval_report.json /
capture.json / artifact_manifest.json / shots/*.png / mock_data/`。
逐步用法与命名约定见 [docs/usage.md](docs/usage.md)，协议细节见
[docs/protocol.md](docs/protocol.md)，失败模式见
[docs/failure_modes.md](docs/failure_modes.md)。

## 安全与隐私

- 脚本不内置任何真实程序路径、手机号、IP、账号、session、个人路径。
- `--program` / `--user-data-dir` / `--data-dir` 必须由调用方显式提供，
  后两者必须是运行内独立目录，绝不指向真实安装/账号数据。
- 仓库内不含任何真实敏感数据；提交前可用
  `grep -rEi '1[3-9][0-9]{8,}|[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' .` 自查。

## 测试

零联网冒烟（内置假 CDP / fake 窗口，覆盖参数、DPI 缩放、尺寸校验、
证据 manifest）：

```bash
python tests/smoke_test.py
```

## 安装为智能体技能

本目录本身即技能目录，放到目标 agent 的 skills 目录下，目录名保持
`visual-agent-harness` 即可（如 `%USERPROFILE%\.trae-cn\skills\...`）。
安装后让 agent 读一遍 [SKILL.md](SKILL.md) 并运行冒烟自检。

## 许可证

[MIT](LICENSE)
