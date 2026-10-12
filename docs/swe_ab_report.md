# SWE 对照实验报告：本地 thinking 开关 × F2P（2026-08-24）

> 实验目的：裁定 `LOCAL_ENABLE_THINKING` 默认值——关思考是"提速解药"还是"能力毒药"。
> 背景：初版报告建议本地默认关思考（提速 9 倍），同时把 F2P 失败归咎于"探索策略"。
> 另一分析指出二者逻辑矛盾：90.7% 轮次在关思考下运行，而失败恰发生在此期间。

## 实验设计（单变量对照）

- 任务：SWE-bench `psf__requests-2317`（`requests.request(b'GET',...)` 字节串 method 修复，
  金标准=双点修复：`models.py prepare_method` + `sessions.py Session.prepare_request`）
- 模型：`qwen/qwen3.8-27b`（唯一模型，单变量=thinking 开关）
- 判据：**只有 F2P**（`test_encoded_methods` 过/不过），不看轮数/命中率/时间
- 环境：测试补丁预应用（消除"应用补丁"步骤混杂）、`MEMORY_TOP_K=0`（消除记忆污染）、
  硬路径约束（消除目录漂移）、全新会话与 checkout

## 结果

| 臂 | 变量 | 尝试数 | F2P | 第二修复点（sessions.py builtin_str） |
|---|---|---|---|---|
| A（关思考） | `LOCAL_ENABLE_THINKING=0` | 4 次独立尝试（40/40/40/13 轮） | **0/4 通过** | **4/4 全漏** |
| B（开思考） | `LOCAL_ENABLE_THINKING=1` | 1 次（29 轮） | **✅ 通过**（1 passed） | **找到并修复** |

### B 臂（开思考）关键过程

1. 读源码定位 method 处理 → 先修 `models.py`（bytes decode）
2. 首测失败（400）→ **对照实验**：str GET→200 / bytes GET→400 / requests.get→200
3. **抓原始 wire 请求行**：`B'GET' /get HTTP/1.1` —— 拿到污染实锤
4. 溯源 `.upper()` / `builtin_str` 调用链 → **锁定 `sessions.py Session.prepare_request` 的 `builtin_str(method)` 把 `b'GET'` 转成 `"b'GET'"`**
5. 修复双点 → F2P **1 passed**；全量回归 135 通过（8 失败中 7 个为 base 既有环境/网络失败，
   1 个 `test_HTTP_302_ALLOW_REDIRECT_GET` 重跑 3/3 通过 = 网络抖动，非修复引入）

### A 臂（关思考）共性

4 次独立尝试全部：只修 `models.py`、漏 `sessions.py`、F2P 失败；其中 1 次连测试补丁都未应用
（113+ 轮内 0 测试就位）。关思考下模型能定位单点，但**无法完成"失败→抓包→溯源→双点"的推理链**。

## 结论（判定规则见设计）

- **关思考 F2P 失败（0/4）、开思考 F2P 通过（1/1）→ `LOCAL_ENABLE_THINKING=0` 默认关闭是错误决策，已回退**。
- "瓶颈在探索策略"结论**作废**：同一模型、同一任务、同一环境，唯一变量=thinking——
  开思考系统性调试（对照实验+wire 抓包）找到金标准修复点；关思考 4 次都停在半修复。
- **本地 27B 的能力边界 = 思考深度**。缓存/内存优化仍然有效（提速、稳定性），但它们是
  "跑得更快"，不改变"能否修对"。

## 已落地变更

- `client.py`：本地 thinking **默认开启**（不发送 enable_thinking=False）；仅
  `LOCAL_ENABLE_THINKING=0` 显式关闭（纯速度场景）。`_is_local_base` 判定不变。
- 测试更新：`test_local_provider_disables_thinking_in_payload` 改为双态断言
  （默认不发 / 显式 0 发 enable_thinking=False）。
- 速度代价（明示）：开思考下本地 27B 每轮 2-13 分钟（实测输出 0.3K-12K tokens @16 tok/s）；
  交互闲聊场景可用 `LOCAL_ENABLE_THINKING=0` 或 9B 快模型路由（fast_model）分流。

## 实验轨迹（可复核）

- A 臂：会话 `88cf178d`（40 轮）、`890b1f88`（40 轮）、`26758406`（13 轮）；checkout `/tmp/swe_lfl_local/ab_a2_requests`
- B 臂：会话 `711226b1`（29 轮）；checkout `/tmp/swe_lfl_local/ab_b_requests`（修复 diff 保留）
- 任务文件：`/tmp/swe_lfl_local/task_a3_requests.md`、`task_b2_requests.md`
