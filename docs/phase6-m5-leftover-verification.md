# Phase6 M5 遗留验证：#3 停止按钮真 DOM 抽查 + #4 残余窗口确定性量化

- 日期：2026-10-13　状态：完成（单次测量口径，非统计结论）
- 脚本：`scripts/phase6_m5_leftover_verification.py`（一次性验证工件，不进 CI）
- 工件：`reports/phase6/m5/STOP_DOM_SPOTCHECK.json`、`reports/phase6/m5/RESIDUAL_WINDOW.json`
- 背景：交付报告 §6 遗留 #3/#4（deepseek-web 真页面环境本会话不可用，
  以「隔离 dev 实例 + 真 webui dist DOM + 桩页面 transport」确定性替代）

## 1. #3 webui 真 DOM 停止按钮（设计 §5.6 真机抽查等效）

### 方法
- 隔离 dev 实例：`build_app(engine=build_test_engine 同款装配 + 慢 FakeLLM)`，
  uvicorn 127.0.0.1:8899（不碰生产 8000）；沙箱 chdir+DATA_DIR+runtime 隔离
  （conftest 批次1-4 同款防部署 env 泄漏：canary/auth/model 泄漏实证过会拒装配）。
- 慢 FakeLLM 缺省无 chat_stream → 走 Phase6 同步通道，8s 窗口。
- Playwright Chromium 真 DOM：`textarea.v2-composer-input` 填写+Enter 发送
  → 等「停止」按钮可见（按「停止」子串匹配，兼容「■ 停止生成」全形态——
  审查实证 dist 内含完整 `■ {停止生成}` 文案，无代差；探针 inner_text 显示
  差异为显示层现象）→ 真点击
  → `POST /api/v1/chat/cancel` → runner.cancel → 引擎窗口轮询 Stop 命中。
- 前端模型预置：`localStorage['lfl.selected.model']='default/fake-model'`
  （/api/v1/models 的 current 兜底字面量 deepseek-flash——routes.py
  `getattr(engine.llm,"model",None) or "deepseek-flash"`，FakeLLM 无 .model——
  不在 fake 池注册表，直接发送会 pool_resolve_failed——action_trace 实证）。

### 结果（单次）
| 指标 | 值 | 门（T2 口径） |
|---|---|---|
| t(click→引擎终态) | **49.3ms** | ≤100ms ✅ |
| t(click→UI 停止按钮消失) | 55.5ms | — |
| 四态·取消在途 | assistant 持久化内容空 + 0 工具 ✅ | 断言通过 |

四态口径说明：取消在途 → 终态 0 字节 0 工具（run_finalizer answer_origin=
program → PROGRAM_FINAL_PROTOCOL_BOUNDARY="" 落盘，代码级支持）；`_CANCELLED_ANSWER`
（「已停止…」）仅随终态事件投递 UI。**限定**：messages 端点实测空行为是本装配特有
（build_test_engine 未注入 `_event_store`，无 program.final 事件水合）；生产装配下
刷新历史会以 program.final 的 full_text 水合为「已停止」文案（routes.py
messages 水合路径），非通用语义。

## 2. #4 残余窗口确定性量化（设计 §4.4 口径）

### 方法
- **#4a 引擎侧下界**（FakeLLM，8s 窗口 t+2s 插话）：runner 驱动 run（/queue 仅入队
  不驱动 run——202≠已启动，首轮实证），queue+interject API 注入；
  残余 = t(下一轮 provider 调用开始, epoch) − hq.received_at。
- **#4b guard 侧**（真实 `DeepSeekWebModelClient` + `_ThreadBoundTransport` +
  桩页面 transport 固定 6s exchange，W3 同款构造；响应键集须与
  `_validate_response` allowed 精确相等——协议校验实证）：
  - 无 cancel 触发（模拟引擎未调钩子/页面无早退）：t=2s 起第二次 chat，
    guard_wait = t(第二次 exchange 进入) − t(第二次 chat 发起)。
  - cancel 触发（M2 契约）：t=2s 调 client.cancel()，第一次调用早退后第二次 chat。

### 结果（单次）
| 场景 | 指标 | 值 | 对照 |
|---|---|---|---|
| #4a | t_effect（插话消费，via=sync_window_poll） | 20.1ms | T1 门≤100ms 同形态 |
| #4a | 引擎侧续答残余 | **1.6ms** | 打断后下一轮立即开始 |
| #4b 无钩子 | guard 等待 | **3990.7ms** | 理论上界 4000ms（剩余窗口）✅ |
| #4b 有钩子 | 早退释放 + guard 等待 | 0.3ms / **0.4ms** | M2 cancel 近瞬时释放 |

### 结论
- §4.4「消费即时、续答受残余窗口约束」的无钩子侧精确成立（3990.7≈4000ms）；
  有 M2 cancel 钩子时残余塌缩到亚毫秒——web 通道续答残余
  = 引擎侧（~2ms）+ guard 侧（无钩子≈剩余 turn ≤120s；有钩子≈0.4ms）。
- 口径注记（审查 C5）：guard_wait = guard 等待 + 毫秒级非 guard 开销
  （`_ThreadBoundTransport._lock`+executor 提交，取 exchange entry 时刻）——
  对 ~4s 场景可忽略；有钩子 0.4ms 为该路径总开销**上界**（结论「亚毫秒」不变）。
- 边界：#4b 为桩页面（固定时长；审查后已对齐真实 M2「取消只作用在途轮次，
  exchange 开始清零取消事件」语义），真实页面残余还含页面实际完成时间；
  停止按钮释放页面仍为 best-effort（deepseek 真页面不可用，维持原判）。

## 3. 过程中实证的事实（方法层，供复用）
1. 脚本环境必须 `sys.path.insert(0, REPO/'src')`——否则可能解析到 `.releases/`
   部署代码（曾误载并触发生产 canary 拒绝装配）。
2. 宿主 LFL 会话 env 泄漏（canary/auth/LLM_MODEL 等）按 conftest 批次1-4 清除；
   `/api/v1/models` 的 current 兜底字面量 deepseek-flash 在 fake 池外，
   前端需 localStorage 预置模型。
3. `/api/v1/chat/queue` 仅入队不驱动 run（S 测试 runner.start 先行）。
4. 同端口多 dev 实例：旧 uvicorn 必须先停（绑定失败时 HTTP 打到旧引擎，
   interject 409 no_live_run 实证）。

## 4. 审查记录
- 独立子代理实读审查（blocking 0 / comment 7，结论 approve）：度量链逐环取证
  （按钮 DOM→cancel 路由→runner→引擎 poll 循环→_CANCELLED_ANSWER 终态→
  落盘链路→hq 戳记→W3 同构→响应键集→沙箱泄漏面），工件数值与代码口径
  逐值交叉核对一致。7 条 comment 全采纳（C1 dist 文案更正、C2 messages
  空行为装配限定、C3 current 来源措辞、C4 桩取消复位、C5 guard_wait 上界
  表述、C6 沙箱加固钉门、C7 sid 断言+状态集精简）；采纳项不影响已测数值
  （审查判定 + 改动面复核：桩复位在 entry 时刻后、env 钉门与默认一致、
  断言强化仅收紧失败面）。

> 数值口径：表中为审查采纳后定版脚本的单次运行（与前次运行 89.2/21.3/1.9/
> 3990.2/0.2ms 同形态，时延单次波动属正常；门判定均不变）。
