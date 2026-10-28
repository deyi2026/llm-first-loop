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

## 5. R5 数据点（本轮不实施，按委派记录）

- dialog 打开期间 `browser_perceive snapshot`：**20.0s 后抛 `RuntimeError: capture_channel_degraded[mode=timeout]; ... session kept (dialog-capable)`**（实测，flow B）。
- 冻结页上 `do=dialog` 全链耗时 **40.2s**（= operate grounding 新鲜快照 20s + adapter 前置 capture 20s，两处超时后各自走回退；dispatch 本身毫秒级）。
- R5 候选（snapshot 在 `_dialog_open` 时短路返回「页面被 dialog 阻塞 + 类型/默认值」）可把上述 20s/40s 压到毫秒级，属行为变更，未实施。

## 6. 未覆盖 / 已知限制

1. `iframe` 内 dialog、`beforeunload`、真实发文站点 confirm、多标签并发 dialog——未测（沿袭判定报告 §7）。
2. R4（click 改 `Input.dispatchMouseEvent`）未做——对外语义变更，需用户单独裁决。
3. R5（冻结页 snapshot 短路）未做（§5）。
4. 冻结页 grounding 回退用的是「最新持久 world」（B' 用例中是 about:blank 的 world）：light-mode 前置把声明版本与自身比对、actuator 恒定绑定精确 target，语义安全；但这是**跨页面状态**的 grounding，属既定 light-mode 语义的延伸，值得在 M2 文档标注。
5. harness 的 `resume_state.page_url` 恒空（scope_facts 投影里 `url:null`）——cosmetic，URL 一致性由 `/json/list` wait_ready 保证。
6. `_dispatch_locked` R3 盲发只试一次、无重试；`No dialog is showing` 之外的 CDP 错误原样透传（不吞）。
7. 环境注记：live 期间曾出现一次 60s 工具超时杀进程导致 target 泄漏，已手动 `/json/close` 清理；结束时 `/json/list` 无 8799 残留、用户标签未动、Chrome 未重启。
