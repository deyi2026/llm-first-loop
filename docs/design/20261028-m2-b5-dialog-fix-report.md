# B5 `dialog` 生命周期缺陷修复回执（M2，2026-10-28）

> 规格：`docs/design/20261028-task009-dialog-verdict.md` §6（R1/R2/R3）；委派补充：R2 端到端（click 工具层 post-capture）与「页面自主弹窗」live 用例。
> 结论先行：**R1/R2/R3 + 工具层端到端全部落地；单测 720 passed（browser 全量）；live 四流全过（click / 自主弹窗 3s / 自主弹窗 300ms 无观察 / 负例）**。commit `fix(B5):`，未 push。

## 1. 变更点（文件 : 行为）

| 文件 | 行为 |
|---|---|
| `src/llm_loop/browser/cdp_host.py` | R1：`capture()` 与 `collect_guard_observation()` 的 except 按 `_classify_connection_loss` 分流——`timeout` **不再 `_drop_session()`**（错误前缀 `capture_channel_degraded[mode=timeout]` / `guard_channel_degraded[mode=...]` 保留，尾部改为 `session kept (dialog-capable)`）；仅 `frame_too_large`/`connection` 仍 drop。`_CONNECTION_LOST_ERRORS` 元组未动 |
| `src/llm_loop/browser/cdp_action_host.py` | R1：`dispatch()` 超时保 session（`CDP mutation timed out; session kept ...`），`settle()` 超时保 session 且 verdict 如实 `unavailable[reason=timeout: ...]`；真断连/1009 仍 drop。R2：`_MutationCdpSession.send(..., early_return_on_dialog=False)` 新增关键字参数（仅 click 路径传 True），等待循环收到 `Page.javascriptDialogOpening` → 事件先入 `self._events` 再抛 `_DialogOpeningInterruptedError`（普通 Exception，刻意不属 `_CONNECTION_LOST_ERRORS`）；click 分支捕获后置 `_dialog_open/_dialog_detail`、返回 `acknowledged=True` + `dialog_opened` 边界事件、不 drop；迟到（陈旧 id）的 click 响应由后续 send 静默跳过。R3：`_dispatch_locked` 的 dialog 门禁从硬拒绝改为「drain 一次 → 仍无则盲发一次 `Page.handleJavaScriptDialog` → Chrome `No dialog is showing` 如实映射回 `dialog_not_open`」；成功即本次动作完成 |
| `src/llm_loop/browser/action.py` | R2 端到端：dispatch 回执含 `dialog_opened` 边界事件 → 跳过 post-capture，回执新增 `post_capture={"skipped": true, "reason": "dialog_open"}`、completeness 增 `post_capture_skipped:dialog_open`（新增字段，非 dialog 场景字段缺席、行为不变） |
| `src/llm_loop/browser/perception.py` | 新增只读助手 `latest_page_resource_ref(session_id)`（最新持久 world 的 resource_ref；never captures） |
| `src/llm_loop/tools/builtin/browser_semantic_operation.py` | `_ground_page`：新鲜快照失败（冻结页）→ 回退会话最新持久 world（`MultiPageAmbiguityError` 不回退，保持歧义拒绝）；无 prior world 则原错误照旧（「无观察无 mutation」不变）。工具描述 B5 段更新（「绝不盲发」→「先探一次」） |
| `tests/unit/test_browser_b5_dialog_lifecycle_v01.py` | 新增 18 条（详见 §2） |
| `tests/unit/test_browser_m2a_presskey_hover_dialog_download_v01.py` | 2 条按新语义有意更新（详见 §2 语义变更声明） |
| `work/lfl-b5-dialog-fix/` | live 页面 ×4、产品工具路径 harness（`live_b5_fix_check.py`）、300ms 变体探针（`fast_variant_probe.py`）、原始证据（`out/live_result.json`、`out/live_run.log`、`out/fast_variant.json`） |

## 2. 单测回执

- **新增** `tests/unit/test_browser_b5_dialog_lifecycle_v01.py`：**18 passed**。覆盖：
  - R1 超时保 session ×3（observation capture / mutation click recv 超时 / settle），断言 `_session is not None` 且 socket 未 close；
  - R1 回归 drop ×5（observation frame_too_large/断连/guard 断连、mutation 断连/frame_too_large）断言 `_session is None` 且 socket closed；
  - R2 click 事件优先 ×2（acknowledged+dialog_opened+状态置位+命令序列 `Page.enable→DOM.resolveNode→Runtime.callFunctionOn`；同 session accept 后陈旧 click 响应被跳过、后续动词正常）；
  - R2 参数化回归 ×1（hover 中插 dialog 事件不提前返回，走旧尾 drain）；
  - R3 ×3（盲发成功=未观测到的 dialog 被处理、无 dialog 映射 `dialog_not_open` 且命令序列恰为 `[Page.handleJavaScriptDialog]`、drain 可见事件时不盲发）；
  - R2 端到端 ×4（adapter 含 dialog_opened → post-capture 跳过且 `backend.calls==1`；无 dialog 边界 → post-capture 照旧 `==2`、无 `post_capture` 字段；operate 冻结页 grounding 回退最新 world 且动词到达 actuator（3 次 capture 全部诚实降级）；空 store 无 prior world → 原错误透传、零 dispatch）。
- **更新** `test_browser_m2a_presskey_hover_dialog_download_v01.py`：**72 passed**（原 70）。
- **全量**：`tests/unit/test_browser_*.py tests/unit/test_smc_browser_*.py` → **720 passed, 0 failed**（5.1s）。
- **外溢检查**：引用被改模块的非 browser 前缀测试 9 个文件 → 90 passed, 13 skipped。
- ruff：被改文件全部通过（`channel_binding.py` 的 UP035 为未触碰文件的既有告警）。

### 2.1 有意语义变更声明（M2-A「零 CDP」保证取消）

`test_b5_actuator_dialog_without_open_dialog_rejects_before_any_traffic`（断言「未开 dialog 时零 CDP、不建连」）按 R3 新语义**有意更新**为 `..._probes_once_then_rejects`：现在命令序列恰为 `[Page.enable, Page.handleJavaScriptDialog]`（一次探针、零 Runtime.*/DOM.*、无重试）。原因（测试内注释 + 本报告双重记录）：**页面自主弹出的对话框**（setTimeout alert / beforeunload，本会话从未观测到 opening 事件）在旧语义下永久锁死、无任何恢复路径；无 dialog 时 Chrome 对 `Page.handleJavaScriptDialog` 回 `No dialog is showing`，页面侧零副作用。`dialog_not_open` 错误码与 guidance 语义不变。`test_b5_actuator_dialog_state_not_reusable_after_accept` 同步更新（lifetime handle 计数 1→2：dismiss + 一次探针）。

## 3. live 正例（产品工具路径，Chrome for Testing 155 / CDP 9229，自建 target 跑完即关）

harness：`work/lfl-b5-dialog-fix/live_b5_fix_check.py`（navigate 用产品 `browser_operate do=navigate`，需 host-owned `LFL_BROWSER_ALLOWED_HOSTS=127.0.0.1`；attest 用 dedicated stub——attestation 路径不在本任务范围）。原始 JSON：`out/live_result.json`（verdict=PASS，2026-10-28T12:17:04→12:18:49）。

### 3.1 A：click 弹 alert（核心断言链）

| 步骤 | 关键回执字段 |
|---|---|
| navigate | compact `status=completed` |
| `browser_perceive snapshot` | 22 objects（含 button `lfl-alert-btn`） |
| `browser_operate do=click` | action_receipt `status=ok`、`boundary_events=[{event:"dialog_opened", detector:"Page.javascriptDialogOpening"}]`、`post_capture={skipped:true, reason:"dialog_open"}`、**elapsed 0.03s**（修复前：5s 超时→drop→20s capture 超时→二次 drop→标签页永久卡死）；actuator `_dialog_open=True`、session 未 drop |
| `browser_operate do=dialog action=accept` | compact `status=completed`；`_dialog_open` 复位 False |
| 恢复读数（snapshot ×2 间隔 300ms） | `t0:50` / `t1:40125`（**父代理判据 #4**：`__t0` 有值=handler 进入，`__t1` 有值=alert 返回后 continuation 执行——页面确实恢复；40s 差值=accept 链路内 2×20s capture 超时，见 §6） |
| 同 target 收尾 | 裸 `host.capture()` 正常返回（keys: dom/ax/frames/...）、**无 `capture_channel_degraded`**；mutation+observation session 均存活 |

### 3.2 B：页面自主弹窗（R3 存在的理由，单列）

页面加载 3s 后 `setTimeout` **自行**弹 alert，无任何 click。先观察一次（19 objects，形成 prior world）→ 等待自弹 → `actuator._dialog_open == false`（从未观测到 opening 事件）→ `browser_operate do=dialog action=accept`：

- compact `status=completed`、action_receipt `status=ok`（**非 `dialog_not_open`**）——`_dialog_open` 为假经 R3 自愈（drain→盲发）成功；
- 页面恢复：`t0:4 / t1:63806`；随后 capture 正常、session 存活。
- 备注：live 侧无法区分「Page.enable 时 Chrome 补投了 opening 事件（drain 分支吸收）」与「纯盲发分支」——两者同属 R3 自愈设计；纯盲发分支由单测 `test_r3_blind_handle_succeeds_for_unobserved_open_dialog` 锁定。

### 3.3 B'：300ms 快弹变体（父代理字面规格，零主动观察）

`dialog_fast.html`（300ms 自弹）：navigate（其自身前置 capture 持久化了 about:blank world）→ 不做任何 snapshot → `do=dialog accept` → **completed**（40.2s），页面恢复（`t1:41682`），capture 正常（`out/fast_variant.json`）。即：连「从未观察过该页面」的字面变体也能经 grounding 回退 + R3 处理。真正的边界（会话 store 全空）由单测锁定为原错误透传、零 dispatch。

## 4. live 负例（零副作用）

plain 页 `do=dialog accept`：action_receipt `status=failed`、`retry.reason="dialog_not_open"`（公共错误码不变）→ 同 target 随后 snapshot 正常（13 objects、镜像文本 `t1:none` 未变）、裸 capture 正常、两个 session 均存活——**无 drop、无页面副作用**。

## 5. R5：dialog 打开期间的观察/门禁快路径（本轮实施）

**规格与实施**（commit `feat(R5)`，另含门禁重构 `refactor(M1 gate)`）：只读探针 `CdpBrowserMutationActuator.dialog_state()`（`download_state()` 同款 fail-open drain，结构 `{schema, open, dialog{type,message≤300,default_prompt,url}}`；message 只回给当前调用、不落盘）→ 三处消费：

| 消费点 | 行为 |
|---|---|
| `browser_perceive` snapshot / vision=evidence | capture 前探测：dialog 打开 ⇒ 毫秒级返回 `observation_status=blocked_by_dialog` + `objects=[]` + 无 `version/world_version`（不伪造世界）+ `guidance` 指向 `do=dialog` |
| `browser_semantic_operation._ground_page` | dialog 打开 ⇒ 直接取 `latest_page_resource_ref()`，不尝试 capture；无既有 world ⇒ 确定性 `dialog_open_no_prior_world`（不伪造） |
| `BrowserActionAdapter` 前置 | verb=dialog 且探针确认 ⇒ 跳过注定失败的全量 capture，进入既有 light-mode（`probe_page_target()` 仍是机械存在门；失败照旧拒绝） |

**实测收益**（同一台机器、同一冻结页），替换 §5 的旧数据点（20.0s / 40.2s）：

| 场景 | 修复前 | 修复后（实测） |
|---|---|---|
| dialog 打开时 `browser_perceive snapshot` | 20.0s 后 `capture_channel_degraded[mode=timeout]` | **55ms** `blocked_by_dialog` |
| 冻结页 `do=dialog accept` 全链 | 40.2s（grounding 20s + adapter 20s） | **140–150ms**（工具层）／**11.3ms**（actuator dispatch） |
| `dialog_state()` 探针本身 | — | **51ms**（返回 `type=alert`、message、url 正确） |
| accept 后页面恢复 | — | 同 target 后续 press_key 正常 ack（冻结解除） |

**边界（实测，别再重复探测）**：
1. 探针只报「本会话已知状态」。若 dialog 在会话 attach **之前**就已打开，`open=False`，仍回落到原 20s 路径；这是刻意的——新 attach 无法廉价得知：冻结页上 `Page.enable` **3.02s 超时**（未完成），而 `Target.getTargetInfo` / `Page.getNavigationHistory` 虽 25ms 可回，但不携带 dialog 信息。
2. 会话在 dialog 打开前已 attach 时，`Page.javascriptDialogOpening` 一定送达（实测 params 完整：type/message/url/defaultPrompt），因此 click 触发与页面自弹两条主路径都有 tier-1 覆盖。
3. 探针异常/未接线 → 一律回落原路径（fail-open），不改变无 dialog 时的行为。


## 6. 未覆盖 / 已知限制

1. `iframe` 内 dialog、`beforeunload`、真实发文站点 confirm、多标签并发 dialog——未测（沿袭判定报告 §7）。
2. R4（click 改 `Input.dispatchMouseEvent`）未做——对外语义变更，需用户单独裁决。
3. R5 已实施（§5），但**只覆盖"本会话已知 dialog"**：attach 前已打开的 dialog 仍走 20s 原路径（探针无从廉价得知，见 §5 边界 1）。
4. 冻结页 grounding 回退用的是「最新持久 world」（B' 用例中是 about:blank 的 world）：light-mode 前置把声明版本与自身比对、actuator 恒定绑定精确 target，语义安全；但这是**跨页面状态**的 grounding，属既定 light-mode 语义的延伸，值得在 M2 文档标注。
5. harness 的 `resume_state.page_url` 恒空（scope_facts 投影里 `url:null`）——cosmetic，URL 一致性由 `/json/list` wait_ready 保证。
6. `_dispatch_locked` R3 盲发只试一次、无重试；`No dialog is showing` 之外的 CDP 错误原样透传（不吞）。
7. 环境注记：live 期间曾出现一次 60s 工具超时杀进程导致 target 泄漏，已手动 `/json/close` 清理；结束时 `/json/list` 无 8799 残留、用户标签未动、Chrome 未重启。

## 7. 本 delta 包含的全部变更（相对生产 main `e10d08ac3`）

审查口径是 `main..HEAD` 的 5 个提交，本文档前 6 节只覆盖 B5/R5 两条主线；其余同批变更在此登记，避免"报告与代码不一致"：

| commit | 内容 | 状态 |
|---|---|---|
| `fix(M2/M3): type 上限移出 schema + D4 绑定降级标注 title_relaxed` | `type` 文本上限从 JSON Schema 的 `maxLength` 移到工具描述 + 服务端校验（schema 层不再截断/拒绝模型输入）；桌面 D4 窗口绑定在标题匹配降级时回执显式带 `title_relaxed`（不静默放宽） | 已实现，单测覆盖 |
| `fix(B5): dialog 生命周期三缺陷修复` | §1–§4 | 已实现 + live 验收 |
| `feat(R5): dialog 打开时观察与门禁快路径` | §5 | 已实现 + live 验收 |
| `refactor(M1 gate): 抽出派发前观察与 dialog 派发` | 函数长度回 ratchet（`action.execute` 475→388、`perceive.execute` 377→350、`_dispatch_locked` 148→113、`build_engine` 2154→2151）；唯一行为修正：兜底分支 `before_raw` 未绑定 → 恒 `{}` | 已实现，1196 passed |
| `merge: 同步生产 main（e10d08ac3）到 R5 分支` | 纯同步合并，无功能变更 | — |

**已知未做**：R4（click 改真实鼠标事件）按用户裁决不做——保留 `this.click()` 对 `display:none`/未布局元素的触发能力，属对外语义取舍，不是遗漏。

## 8. 独立审查（REVISE）响应

首轮 Host 审核结论 `REVISE P0=0 P1=1 P2=5`（`review_tail` 明确 P1 为"报告与代码不一致"）。逐条处置：

| 编号 | 审查意见 | 处置 |
|---|---|---|
| **P1** | §5 声明 R5 未实施，但 delta 内已实现 R5；本批还夹带 D4 降级与 schema 变更未登记 | §5 改写为"已实施 + 实测数据 + 边界"；新增 §7 表列全 5 个提交（type 上限/D4、B5、R5、门禁重构、同步合并），审查口径 `main..HEAD` 与文档一一对应 |
| P2-1 | `_ground_page` 回退 `except Exception` 会吞掉无关异常并落到旧世界 | 收窄为 `except RuntimeError` + `capture_channel_degraded` 文本门；其它异常原样透传。新增负例测试 `test_ground_page_non_capture_failure_propagates_...` |
| P2-2 | `dialog_state()` 在 `_dispatch_lock` 外 drain，与并发派发交错 | 保持现状并说明：probe 只 drain 本会话已到达事件、不 flush、不发命令；与既有 `download_state()`（perceive 侧已在用）同一模式。争用后果是"读到的状态可能比 dispatch 早一帧"，receipt 不据此断言页面内容，可接受 |
| P2-3 | dialog 动作未校验枚举 | `_dialog_accept_flag()` 在 actuator 边界只接受 `accept|dismiss`，其它值 `invalid_argument` 且零 CDP 命令（测试覆盖） |
| P2-4 | 工厂接线未被测试覆盖 | 新增 `test_attach_dialog_probes_wires_both_tools`：断言单点同时挂到 perceive 与 operate，且绑定同一 actuator 方法 |
| P2-5 | 提交物/证据含绝对路径与失效 scratch 文件名 | 报告与 live 日志的绝对路径已替换为 `$CODE_ROOT/$RUNTIME_ROOT/$SCRATCH`；`.tmp-ci` 门禁 scratch 目录已清理 |


