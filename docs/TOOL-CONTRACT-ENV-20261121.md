# 工具契约与环境事实（EVO-20261121-efa320ab）

> 适用范围：`execute_command` / `read_file` / `read_image` / `cdp_probe` / 视觉链路。
> 定位：把**运行时可核事实**写进工具契约与本文档，避免模型把"环境假设"当"事实"使用。
> 证据：本机（Deepin / Linux）实测，2026-11-21 头条发布任务；回归用例见文末。

## 0. 本次演进解决的问题

| 症状 | 机制性根因 | 本演进的对策 |
|---|---|---|
| 视觉模型点错按钮 | 回执里「内容识别」的坐标与元信息里的真实像素**不是同一坐标系**，且无换算依据 | `read_image` 固定输出**确定性坐标契约**（原图/裁剪/送检尺寸/缩放系数/换算式） |
| 大图识别整体降级 | ≥2000px 的图在视觉后端稳定失败（本机三张全部降级） | `WEB_VISION_MAX_SIDE` + 本地降采样 + 失败兜底重试 |
| 「Chrome 有没有开调试端口」无法回答 | 没有任何工具能发现 CDP 端点 | `cdp_probe` 只读探针 |

## 1. 三条运行环境事实（execute_command 沙盒）

1. **单次调用墙钟上限约 60s**：超时回执**不代表**后台进程已被杀死。长任务用
   `run_in_background=true` 拿 `job_id`，再用 `job_output` 查询、`wait` 等终态。
2. **`/tmp` 视图不共享**：沙盒的 `/tmp` 与宿主的 `/tmp` 不是同一目录。沙盒内写入的
   `/tmp` 文件，宿主侧工具（`read_file` / `read_image`）读不到；反之亦然。需要跨边界
   传递的产物请落在**工作区**目录内。
3. **沙盒内解释器路径不可执行**：`releases/*/venv/bin/python` 等软链指向沙盒外的
   `uv` 安装目录，在沙盒内执行报 `not found`。沙盒内请用系统 `python3`（无第三方库）
   或自行安装在沙盒可见路径的解释器；需要第三方库时在**宿主**侧建 venv 后再调用。

## 2. `cdp_probe`：CDP 端点可达性探针（只读）

命名说明：探针**不进入 `browser_*` 页面能力家族**——既有能力身份契约要求 provider-visible
browser 面恰好「一只眼 `browser_perceive` + 一只手 `browser_operate`」；本探针读不到页面、
不能写页面，只是环境诊断，故独立命名以保持该契约原样不动。

用途：确认"本机 Chrome 是否暴露了 CDP 端点、地址是什么"，从而决定
`browser_perceive` / `browser_operate` 能否注册。

- 发现来源：① 已配置的 `LFL_BROWSER_PERCEPTION_CDP_URL` ② 常见端口（9222/9223/9229）
  ③ Chrome 用户数据目录下的 `DevToolsActivePort`（Chrome 开远程调试时的落盘事实）。
- 只读：仅取 `/json/version` 与 `/json/list` 的**元信息**（浏览器版本、协议版本、目标计数），
  **不回传**页面标题/URL 等页面内容；只探 loopback，非 loopback 目标直接拒绝。
- **不放宽 opt-in**：探针不改配置、不启动浏览器（补用例断言）。`browser_perceive` / `browser_operate`
  仍需显式设置 `LFL_BROWSER_PERCEPTION_CDP_URL` 并重启服务后才会注册（既有 profile class
  门禁保持不变）。
- Chrome 136+ 政策：对**默认用户目录**禁用 `--remote-debugging-port`，需以非默认
  `--user-data-dir` 启动才暴露 CDP 端点；因此"已登录的默认配置"无法直接开远程调试。

## 3. `read_image` 坐标契约

回执固定包含一行确定性契约：

```
[坐标契约] 原图=400×300 裁剪=(10,20,100,50) 送检=100×50 缩放=1.000 换算=原图坐标=(送检坐标÷缩放)+裁剪偏移(10,20)
```

- `crop={x,y,w,h}`：按**原图像素坐标**裁剪后送识别；越界/非法参数 → `FAILURE` 并给出明确提示。
- `送检`：实际送进视觉后端的尺寸（大图会被本地降采样，故可能小于裁剪尺寸）。
- `缩放`：`送检尺寸 / 送检前尺寸`；模型自报坐标按 `送检坐标 ÷ 缩放 + 裁剪偏移` 换算回原图。
- `[坐标]` 块：模型自报 bbox 的结构化输出，**明确标注"模型自报，未经验证"**——它只是定位线索，
  不是像素级校验结论。

## 4. 视觉链路大图降采样

- `WEB_VISION_MAX_SIDE`：长边像素阈值，默认 `1568`；`0` = 关闭降采样与兜底重试。
- 超阈值大图在**本地**降采样（只缩小、不放大、不改原文件；JPEG 保持 JPEG，其余转 PNG）。
- 识别失败时按「再降采样一半」兜底重试一次；两次都失败如实报错，不伪装成功。
- 结果经 `describe_image_detailed()` 结构化回报：`geometry.source_* / input_* / downsampled`，
  `fallback_used` 标记是否走过兜底。

## 5. 回归用例（RED→GREEN）

- `tests/unit/test_read_image_geometry_contract_v01.py`：crop 越界 fail-closed、坐标契约、
  bbox 换算、视觉失败仍给契约、提示词透传。
- `tests/unit/test_vision_downsample_v01.py`：阈值生效/禁用、兜底重试、总失败抛错、
  送检尺寸写进提示词。
- `tests/unit/test_cdp_probe_v01.py`：可达/不可达如实回报、不回传页面内容、非 loopback 拒绝、
  `DevToolsActivePort` 发现、工具回执含 opt-in 指引。

## 6. 独立审查后的修复（P1/P2）

首轮独立审查（不同模型只读子代理；Host `review_admission` 因 `reviewer_models_unconfigured`
不可用）判定 FAIL，给出 3 个 P1 + P2 若干，均已修复：

- **P1-1**：`browser_probe` 无条件注册破坏「一只眼一只手」能力身份契约（4 处既有测试红）→
  改名 `cdp_probe`，既有契约与测试原样不动。
- **P1-2**：`read_image` 改调 `describe_image_detailed` 后，既有 `test_read_image.py` 的 mock
  目标失效（成功路径与降级指引路径实际已不被测到）→ mock 目标迁移到新 seam，断言意图不变。
- **P1-3**：`read_image.execute` 161 行触发 function-lines ratchet → 拆分函数降到 60 行级，
  **不抬 baseline**。
- **P2**：探针 timeout 上限 10s；非 loopback 直接拒绝；视觉兜底重试覆盖 httpx 传输层错误；
  失败路径「送检尺寸」标注为推定；降级指引判定归一；compact 描述收紧（控 schema token 成本）；
  60s 表述精确化（`TOOL_TIMEOUT_S` 可配、creative 模式 ×1.5）。
