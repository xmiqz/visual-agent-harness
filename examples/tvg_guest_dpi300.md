# 例子：TVG 游客态 + DPI 300% 整窗验收

本例展示如何把本 harness 用在 TVG（tg-video-downloader 的 WebView2 前端）
的真实场景上。**所有敏感信息均已脱敏**：不出现真实手机号、IP、账号、
session、个人路径；`--program` 用占位路径，真实接入时换成 TVG 的宿主
exe 即可。

## 场景

- 状态：游客态（未登录），展示 mock 任务列表，隐藏非交互错误条。
- DPI：PerMonitorV2 下 300%（`content_scale=3.0`）。
- 逻辑窗口：1280×800。
- 期望物理尺寸：1280×3=3840，800×3=2400。

## 1. 真值（人工从规范导出，不为脚本臆造）

`examples/` 内置场景 `guest-with-tasks` 即对应此例：

```json
{
  "auth_state": "guest",
  "logical_window": {"width": 1280, "height": 800},
  "content_scale": 3.0,
  "expected": {
    "guest_banner_present": true,
    "login_prompt_present": false,
    "non_interactive_error_bar_hidden": true,
    "title_text": "示例演示程序",
    "task_list": [
      {"id": "task-001", "title": "示例任务一", "progress": 0},
      {"id": "task-002", "title": "示例任务二", "progress": 50}
    ]
  }
}
```

## 2. 运行（真实接入把 Host.exe 换成 TVG 的 WebView2 宿主）

```bash
python scripts/harness.py \
  --program "C:/path/to/TvgWebViewHost.exe" \
  --url "https://example.invalid/demo" \
  --scenario guest-with-tasks \
  --out-dir run --content-scale 3.0
```

TVG 侧需按 [docs/usage.md](../../docs/usage.md) 的约定实现演示态注入：
读取 `VAH_MOCK_DATA_DIR` 加载 `mock_state.json`、按 `VAH_CONTENT_SCALE`
设置根缩放、隐藏非交互错误条、渲染游客横幅与 mock 任务（选择器需包含
`data-guest-banner` / `data-task-item` 等，供 `cdp_eval` 断言）。

## 3. 截图命名

按命名约定（harness 自动生成）：

```
tvg__guest-with-tasks__guest__dpi288__1280x800__3840x2400.png
```

- `dpi288` = 96 × 3.0（系统报告的逻辑 DPI；>250% 时系统会钳制，故真实
  DPI 以显示器为准，命名仅作记录）。
- `1280x800` 逻辑尺寸，`3840x2400` 期望物理尺寸；实际截图尺寸须与之匹配
  （容忍 1px），否则 `capture_window` 报 `size_match=false` 交人工复核。

## 4. 预期结论

- 证据齐全且自动断言通过 → `verified`（rc=0），进入人工终验。
- 若 300% 下物理尺寸 ≠ 3840×2400 → `unverified`（rc=2），人工核对显示器
  真实缩放与窗口是否最大化后再下结论。**绝不因为"看起来差不多"就标通过。**

## 5. 自测用的等价后端

仓库内 `examples/demo_host.py` 是一个与 harness 约定一致的演示宿主，可在
没有真实 TVG 二进制的机器上端到端验证全流程；真实接入时无需改动本
harness 任何脚本，只需把 TVG 宿主作为 `--program`。
