# 方案：模型切换首轮瘦身（slim-first）——跨模型切换的缓存成本控制

> 状态: **已废弃（superseded by DESIGN-v3）**
> 本文件为 v1/v2 演进中间态，已被 `DESIGN-v2-slim-first-model-switch-cache-cost.md`（v2 定稿）与 `DESIGN-v3-ai-driven-context-switch.md`（AI 主导版）取代，仅作历史参考。 | 2026-08-20 | 关联: `docs/ARCHITECTURE-cache-stable-rules.md`（缓存稳定总纲）、EVO-20260820-196d87ed/0b96348d（命中率统计与治理分层）
> 触发: 用户拷问"切换模型第一轮必 miss，成本 30 倍（hit 0.05/M vs miss 1.5/M），如何让切换成本可控、后续稳定"
> 修订记录: v2 采纳评审 P1-P8——P0: 锚点推进描述修正（§1.2/反例4）、provider_id 统一 model_used（§2.2 ①）；P1: MIN_CHARS 实现、切回命中假设修正、归因标注 slim_first；P2: 轮数按字符、验证/回退补全

## 0. 问题定义

模型切换（`switch_model` / web 下拉 / fallback 切模型）时，**切换后第一轮必然全量 miss**：

- 不同 provider = 不同服务端缓存池（DeepSeek / MiniMax 各自独立）
- 同 provider 不同模型 = DeepSeek 按模型维度缓存（flash 与 pro 不共享前缀）
- 第一轮发送的**全部历史**在新缓存池里无任何前缀 → 按 miss 价计费

**成本量化**（长历史 100K 前缀）：

| 场景 | 第一轮成本 |
|---|---|
| 切换前稳定（命中） | 100K × 0.05/M ≈ $0.005 |
| 切换后第一轮（全量 miss） | 100K × 1.5/M ≈ **$0.15（30 倍）** |
| 单次切换额外代价 | ≈ **$0.15**（历史越大越贵） |

## 1. 方案核心：切换首轮瘦身 + 慢预热

### 1.1 一句话

切换检测到新 provider/model 时，**先写"尾部锚点"**——第一轮只送最近 N 轮短历史（瘦身），miss 成本按短历史计；后续轮次在尾部锚点基础上追加新轮，前缀在新缓存池内逐步建立 → 命中率回升且稳定。

> **修订注（2026-08-20 评审 P1）**：锚点**不自动推进**（见 §1.2），早期历史不自动回来——这是特性不是缺陷，靠 archive 检索 + 任务摘要帧找回。

### 1.2 为什么第二轮起就稳定（机制推导，修订版）

- system 前缀**字节不变**（`build_system_prompt()` 与模型无关，见 ARCHITECTURE-cache-stable-rules L0）
- 新 provider 第一轮发送 = `system + 尾部短历史`——该字节串在**新缓存池首次出现** → 完全 miss
- 第二轮发送 = `system + 尾部 + 新增1轮`——**前缀 = 第一轮已提交字节** → 第一轮部分命中
- 第三轮继续 → 前缀渐长、命中率渐高（**慢预热**，与前缀长度成正比）
- **锚点保持固定**：`build.py:208-222` 锚点推进仅在归档路径（超预算触发 `anchor_box`）发生；正常不超预算时锚点永不移动 → 历史窗口固定在尾部 N 轮，**早期历史不自动回来**（经 `search_archive` 检索找回；这是缓存友好设计的代价，与正常会话压缩行为一致）
- **同 provider 内切回**（flash→pro→flash）：若 flash 之前也是 slim-first 锚点（尾部），切回时发送同一字节前缀 → DeepSeek 池内 **TTL 未过则直接命中**；若 flash 之前是全量锚点（anchor=0），尾部前缀与之不匹配 → 仍 miss（受控于 slim-first 的 miss 规模）。**结论：切回是否命中取决于"上次该模型的前缀形态"，不可假设总是命中**

### 1.3 成本对比（长历史 100K 前缀，尾部 10 轮 ≈ 20K）

| 方案 | 第一轮发送 | 第一轮成本 | 省 |
|---|---|---|---|
| 现状（全量历史） | 100K miss | ~$0.15 | — |
| **slim-first** | 20K miss | **~$0.03** | **~80%** |

> 注（评审 P7）：`history.py` 的 `reasoning_tail` 会再瘦身尾部思考链 → 实际发送比表格预期更短，节省可能 >80%（利好，未计入表格）。

## 2. 实现设计（复用现有锚点机制，改动小）

### 2.1 现有机制（已具备，无需新架构）

- `sess.history_anchors[provider_id]`：按 provider 分桶的历史起点（P1-10，session.py 持久化）
- `build_history_messages(history_anchor=...)`：锚点决定历史窗口起点
- engine.py 452：模型切换检测点（`model_used != _cache_last_model`）

### 2.2 改动点

**① engine 切换检测处（452 附近）——写初始锚点**

> **修订注（评审 P2）**：provider_id 口径必须与 build.py 读锚点一致。现状 build.py:59 用
> `planned_label`（计划标签），engine 452 用 `model_used`（routing 后实际，含 fallback 降级）——
> fallback 时两者不同 → 写入键读不到 → 瘦身静默失效。**统一为 `model_used`**（实际模型分桶，
> 同步改 build.py:59 的 `provider_id = model_used.partition("/")[0]`；顺带清理 build.py:57-58 重复行）。

```python
# engine 切换检测处（452 附近）
if model_used and model_used != self._cache_last_model:
    new_provider = model_used.partition("/")[0] or "default"
    if self._cache_last_model is not None:
        self._cache_monitor.reset(
            reason=f"model_switch_slim_first:{model_used}",  # 评审 P6: 标注策略性 miss
            clear_buckets=False,
        )
    anchors = sess.history_anchors or {}
    if new_provider not in anchors:
        # slim-first: 新 provider 首轮瘦身——尾部 N 轮 + MIN_CHARS 下限（评审 P3）
        tail_start = max(0, len(sess.messages) - SLIM_FIRST_ROUNDS * 2)
        tail_chars = sum(len(m.content) for m in sess.messages[tail_start:])
        while tail_start > 0 and tail_chars < SLIM_FIRST_MIN_CHARS:
            tail_start -= 1
            tail_chars += len(sess.messages[tail_start].content)
        anchors[new_provider] = tail_start
        sess.history_anchors = anchors
    self._cache_last_model = model_used
```

```python
# build.py:59 同步改（统一 model_used 口径）——顺带清理 57-58 重复行
provider_id = model_used.partition("/")[0] or "default"
```

**② 参数**（env 可调，默认保守）

| 参数 | 默认 | 说明 |
|---|---|---|
| `SLIM_FIRST_ROUNDS` | 10 | 切换首轮保留的尾部轮数（0=关闭瘦身=现状） |
| `SLIM_FIRST_MIN_CHARS` | 20000 | 尾部锚点最低保留字符（防过度瘦身丢任务上下文；短对话不足时前移锚点补足） |

> **修订注（评审 P5）**：`N 轮 ≈ 2N 条消息` 假设脆弱（工具密集轮一轮可 7-10 条）。
> 实现按**字符数**定锚点更稳（`MIN_CHARS` 为主、ROUNDS 为起始猜测），或按 user/assistant
> 角色边界切分。落地时以 `MIN_CHARS` 为硬下限、ROUNDS 仅作初始值。

**③ 任务连续性保障**（关键，防"反例1"）

- 尾部 N 轮已含最近对话（任务进度通常在最近几轮）
- system 尾部注入（memory/快照/经验，GATE_NOTE 模式转 user）不占前缀，**新模型第一轮即能看到任务上下文**
- 若任务依赖更早历史：`SLIM_FIRST_ROUNDS` 调大，或配合"任务摘要帧"（切换前在 system 尾部打一条任务状态摘要，随锚点一起保留）；更早历史经 `search_archive` 检索找回（评审 P1——锚点不自动推进，早期帧不会自己回来）

## 3. 边界与反例（拷问出的诚实面）

### 反例 1：瘦身过激丢任务上下文
只留 1-2 轮时，新模型可能看不到任务起点（如"42→52→最终52"需看到第1步）。
**对策**：N 默认 10 轮 + `SLIM_FIRST_MIN_CHARS` 下限 + 尾部注入含任务帧。

### 反例 2：TTL 过期后切回仍 miss
切回 deepseek 时若 TTL（~10min）已过且无并发会话保温 → 前缀过期 → 也 miss。
**对策**：这是 provider 缓存 TTL 物理限制，slim-first 不解决首次 miss，只控制 miss 规模；
切回本身也可受益于 slim-first（同样写尾部锚点）。

### 反例 3：频繁切换仍累计成本
每切一次烧一次 miss 价，slim-first 只降单价不降次数。
**对策**：配合治理层——任务边界才切换（简单问答 flash / 深度分析 pro），避免轮内来回切。

### 反例 4：尾部锚点前缀与"全量模式"分叉（修订版，评审 P1/P4）
slim-first 建立的前缀 = `system + 尾部历史开头`；若该模型此前是全量锚点（anchor=0），切回时
发送尾部前缀与之不匹配 → 仍 miss（受控于 slim-first miss 规模）。**锚点不自动推进**（build.py
仅归档路径推进）→ 早期帧首轮即被裁、不会自动回来。
**对策**：早期历史经 `search_archive` 检索找回 + 任务摘要帧随锚点保留；不依赖"切回自动命中"。

### 反例 5（评审 P8）：并发会话保温交互
slim-first 在新 provider 池建立"尾部前缀"，与该 provider 既有会话的"全量前缀"是**不同缓存条目**，
互不保温——若用户同时用全量会话 + slim-first 会话，两者各自独立缓存，无协同。
**对策**：如实接受（缓存按字节前缀隔离是 provider 机制）；若需共享，用同一锚点策略。

### 反例 6（评审 P6）：策略性 miss 污染统计
slim-first 首轮 miss 是**主动瘦身**（非缓存失效），计入模型桶会拉低该模型命中率统计，
可能误触发 `force_head_keep` 等干预。
**对策**：`reason="model_switch_slim_first"` 单独标注，首轮 miss **不进桶**（或单独计数
`slim_miss_tokens`），与真实缓存失效区分。

## 4. 与现有机制的衔接

| 现有 | 衔接 |
|---|---|
| `ARCHITECTURE-cache-stable-rules.md` | 本方案是其"切换场景"的具体化（总纲覆盖前缀稳定，本方案覆盖切换首轮成本） |
| `history_anchors[provider]` | 直接复用，只新增"首轮写尾部锚点"；provider_id 统一为 `model_used`（评审 P2） |
| cache_health 分桶统计（已落地） | 首轮 miss **排除出桶**（`slim_miss` 单独计，评审 P6），不拉低该模型真实命中统计 |
| cache_guard `reset_session` | 不变（本地统计归零，与成本无关） |

## 5. 验证方法

1. **镜像验证**：切换 deepseek→minimax，抓第一轮 payload 长度（应≈尾部 N 轮而非全量）；
   对比切换前后命中率曲线（第一轮~0%，第 2-5 轮回升）
2. **成本核算**：记录第一轮 miss token 数，对比全量模式（应省 ~80%）
3. **任务连续性**：三步任务中途切换（复用 42→52→52 实测场景），确认新模型能接上
4. **回归**：无切换场景零行为变化（SLIM_FIRST_ROUNDS=0 兜底），既有 151 测试通过
5. **评审补项（反例3/4）**：切换频次 vs 累计成本曲线（验证"只降单价不降次数"）；
   锚点前缀与全量前缀分叉的字节对比（抓 payload 前缀 diff）
6. **归因检查（评审 P6）**：slim-first 首轮后模型桶命中率**不被拉低**（slim_miss 独立计数）

## 6. 落地路径（MIRROR 协议）

```
镜像实施（engine.py 452 写锚点 + build.py:59 统一 model_used + env 参数）
→ 镜像验证（§5 六项）→ 提交审批 → 主区同步 + 全量回归 → 重启生效
```

### 回退方案（评审补项，必须完整）

- `SLIM_FIRST_ROUNDS=0` **只关闭新写入**，已持久化的 `sess.history_anchors[new_provider]`
  仍残留 → build.py 读锚点不检查 env 开关 → 该 provider 仍用尾部锚点。**回退必须清理**：
  - build.py 读锚点时检查 `SLIM_FIRST_ROUNDS`：为 0 时忽略锚点（回到全量行为）
  - 或回退脚本清空 `history_anchors` 中 slim-first 写入的键
- 灰度策略：先在镜像开小轮数（N=5）观察命中曲线与任务连续性，再逐步调大
- 监控指标：命中率回升曲线、瘦身触发频次、slim_miss 占比（架构状态可观测）

> 注：本方案只控制**切换首轮 miss 的规模**（成本），不改变"切换必 miss 一次"的物理事实；
> 稳定性靠既有前缀稳定机制（system 固定 + 尾部追加），本方案是成本侧的补充。
