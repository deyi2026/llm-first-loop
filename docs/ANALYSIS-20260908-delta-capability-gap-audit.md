# Delta Capability Matrix / Gap Audit（基于现有实现的差量审计）

日期：2026-09-08（v1.1 修订同日）
版本：v1.0 → v1.1（按外部复核意见 A1–A7 修订，记录见 §0-6）
性质：只读审计（未改动任何实现代码；v1.1 修订仅涉及本文档自身）
输入：LFL-LoopX-借鉴分析建议书复核 + 用户裁决（Phase A 从"从零盘点"改为"基于现有实现的 Delta Gap Audit"）
工作区：本仓库（llm-first-loop-mirror）检出，HEAD 6762f28（证据 file:line 均指此检出）

## 0. 结论摘要

1. **四套机制（事件顺序/版本冲突/幂等回执/证据完整性）在 FileService 覆盖面内已基本"已有"，且比建议书假设更完整**：edit 路径在锁内完成 版本前置→基线字节复读→prepared 必须持久才写（fail-closed）→原子替换→observed 回执；prepared-only 状态可由查询服务用当前字节对账恢复。**条件句（v1.1，A7）**：本条及 §4 的"已覆盖"扣除均以 P10 各记录面连续性不变量成立为前提，而 P10 逐项待验；P9 的 `repeat_interval` 周期重放亦属未细核的重复副作用面。
2. **真实缺口集中在 FileService 之外**：`execute_command`（前台/后台；**可写任意可达路径而非仅工作区**，见 G1 修订）、`dsh_task`（cwd 指向工作区时，另有盲重放面）的写盘无版本前置、无锁共享、无 prepared→observed 回执——这是 R01/R02 扣除 P1–P4 已覆盖部分后的剩余主缺口（G1/G3）。
3. **并发面：机制大多已有、验证缺失**。SubAgent 与主循环共享同一 ToolRegistry→同一 FileService 单例（同锁+同版本序）；子代理有自己的 WAL、topology/delivery/settle 回执与 generation steering。缺的是 P4 级并发写验证（G2a），不是机制；跨进程互斥的前提条件（双方共享同一 data_dir/lock_root）另立为 G2b。
4. **恢复后模型协议采用不稳定**（用户 P4 运行时结论）：机械能力存在，但恢复后的模型不稳定续用 `snapshot + expected_snapshot_ref` 协议——属契约层缺口（G4），非机械层。
5. 不应实现项维持并扩充：不建 canonical event store/第二事实源（docs/continuity.md 已声明 transport-only）、不做通用操作 ID 框架、不禁止 shell。
6. **v1.1 修订摘要（按外部复核 A1–A7）**：①闭集补 P11 `codearts_dispatch`（factory 直注册的一等副作用工具；v1.0"§2 即初始闭集"的完备性声明随之修正，见 N2）；②G1 改写为"写任意可达路径"；③G3 增补盲重放与后台无审计面；④G2 拆为 G2a（进程内 fault-injection 验证）/G2b（跨进程 data_dir 一致性前提）；⑤G8 已关闭（Web 进程自带完整引擎）并补记 v1.0 漏记机制 run_lease；⑥§3"版本前置=已有"注明 expected_snapshot_ref 为可选参数；⑦证据路径统一补 `src/llm_loop/` 前缀（v1.0 裸文件名 grep 不可复现）；⑧补记两项"该记功而未记"的存活边界（见 P2/P3 行）。

## 1. 方法与标记

- 四态：**已有**（源码可证）/ **部分覆盖**（机制存在但有边界或未验证）/ **缺失** / **不应实现**（明确排除并给理由）。
- 用户提供的 P4 运行时结论（stale write 被拒、人工修改保留、完成写不重放、恢复后协议采用不稳定）标注为〔用户核证〕；本次源码只读核对的标注为〔源码〕。
- v1.1 修订轮新增的源码引用均在落笔前重新 grep 验证（路径含 `src/llm_loop/` 前缀）；v1.0 原有行号未逐条复跑，仅修正路径。

## 2. 副作用执行者与写路径总表

| # | 执行者/路径 | 现状要点 | 证据 |
|---|---|---|---|
| P1 | `edit_file`（模型） | FileService.edit：每路径锁内 期望快照解析（字节不等→VersionConflict）→match/replace→diff→基线读者+**锁内基线字节复读**（BaselineChanged；注释明确 mtime/size 仅旧式竞态检测，同尺寸同 mtime 不放过）→`effect_sink.prepared` 必须持久否则 EffectPreparedUnavailable（**写前 fail-closed**）→临时文件原子替换→`observed` 回执（失败如实置 receipt_state=recording_failed）。另有 symlink 写防护（fail-closed）。WAL sink 经 `current_tool_effect_binding()` 绑定（tools/builtin/edit_file.py:190-195） | src/llm_loop/workspace/file_service.py edit 序列；src/llm_loop/tools/builtin/edit_file.py:100-195 |
| P2 | `execute_command` 前台 | 无 FileService/无 effect sink/无版本前置；子进程环境 scrub 已有。**存活边界（v1.1 补记，该记功未记）**：超限/异常路径先 `os.killpg` 整树 SIGKILL 再返回拒绝（无 false-success），JobRegistry 有 terminate 钩子防孤儿——缺口限定在**写归因缺失**，非进程存活泄漏 | src/llm_loop/tools/builtin/execute_command.py:95-125,192-196 |
| P3 | `execute_command` 后台 | JobRegistry 提供持久句柄（JobDurabilityError/JobLimitExceeded），但**写盘效果仍无回执事件**；进程存活边界同 P2 | src/llm_loop/tools/builtin/execute_command.py |
| P4 | human Web 编辑 | HumanFileOperationService：request_id+request_sha256 幂等、expected_snapshot_ref 前置、EVENT_HUMAN_FILE_EDIT_PREPARED/OBSERVED/**REJECTED**（拒绝也是回执） | src/llm_loop/workspace/human_file_ops.py:24-26 |
| P5 | SubAgent（含 workflow local step） | 与主循环共享同一 ToolRegistry→**同一 FileService 单例**（factory.py:649 唯一实例，662/789 共享）；自身 ToolExecutionJournal（runner.py:131，与主循环同一 WAL 契约，journal 文档串明确 "shared by LoopEngine and SubAgentRunner"）+ topology/delivery/tool-execution journals + generation steering + settle_committed_receipt；批内并行调用有 `activate_effect_binding_for_call` 按 tool_call_id 归属 | src/llm_loop/subagent/runner.py:73-131；src/llm_loop/core/tool_execution_journal.py:75-91；src/llm_loop/factory.py:649,662,789,1380 |
| P6 | workflow codearts | 远端调度，内部未核〔本次未核〕 | src/llm_loop/tools/builtin/workflow.py:267 |
| P7 | `dsh_task` | 外部进程、独立会话；任务文本 `_redact` 脱敏、audit jsonl（**fail-open**）、JobRegistry 后台化；对指定 cwd 的写入**完全绕过 FileService**；非 0 退出码→新 session 盲重试至多 3 次、无幂等栅栏，后台模式无 audit（v1.1 补，详见 G3） | src/llm_loop/tools/builtin/dsh_task.py:1-11,15,41,158-159,215-216 |
| P8 | Feishu outbound ×3 | 限速/白名单/confirm 语义存在；engine/fallback 存在 fallback_receipt 机制〔细节未核〕 | src/llm_loop/feishu/handlers.py；src/llm_loop/core/loop/engine_services/fallback.py |
| P9 | `schedule`/`schedule_cancel` | ScheduleStore 持久化；幂等/重放语义未细核；`repeat_interval` 周期重放本身构成重复触发面，未细核（§0-1 条件句） | src/llm_loop/tools/builtin/schedule.py:66-72,192-217 |
| P10 | 记录面写（goal/task/experience/synopsis/evolution/skill） | 各自 durable store；回执与幂等语义程度不一，逐项待验 | 工具面 |
| P11 | `codearts_dispatch`（模型直达；v1.1 补） | **v1.0 闭集漏项（A1）**：factory 直注册于 registry 的一等工具（非 P6 的 workflow 步执行器），描述自述流水线触发/部署/远端仓库操作——不可逆远端副作用。缓解项：人工审批门+无人值守默认拒绝+远端五态回执；**本地无 prepared→observed WAL 对账〔未核〕**。同族直注册的还有 `codearts_cancel`（亦属副作用类，并入 P11 观察）、`codearts_capability`/`codearts_status`（查询类，不入闭集） | src/llm_loop/factory.py:1490-1493（导入）、1533-1536（直注册）、1556-1569（审批回调：无人值守 fail-closed） |

## 3. 机制 × 路径矩阵

| 机制 | P1 edit_file | P2/P3 shell | P4 human | P5 subagent 文件写 | P7 dsh | P8 feishu | P9/P10 记录面 | P11 codearts_dispatch |
|---|---|---|---|---|---|---|---|---|
| 版本前置 | **已有（可选）**：expected_snapshot_ref 为可选参数（src/llm_loop/tools/builtin/edit_file.py:105,125,177,199），无 ref 时守卫退化为锁内基线字节复读（G4 已证采用不稳定，故此"已有"不能按"恒被使用"读） | 缺失 | **已有** | **已有**（共享同一 FileService） | 缺失 | 不适用 | 不适用/待验 | 不适用（远端资源） |
| 锁+基线复读 | **已有** | 缺失 | **已有** | **已有**（同锁同实例） | 缺失 | 不适用 | — | 不适用 |
| prepared→observed durable | **已有** | 缺失 | **已有**（含 REJECTED） | **已有**（同一 WAL 契约） | 缺失（仅 audit jsonl，fail-open；**后台模式连 audit 也不做**，v1.1 补） | 部分 | 部分 | 部分（远端五态回执〔未核〕；**本地无 WAL 对账**） |
| 崩溃 unknown 对账 | **已有**（prepared-only 可按当前字节对账恢复，_current_prepared_state） | 缺失 | **已有** | **已有**（机制） | 缺失 | 待核 | 待验 | 缺失〔未核〕 |
| retry/幂等 | **已有**（retry_tool 全包裹 + expected_snapshot_ref 天然幂等） | 缺失（且**不应**通用化） | **已有**（request_id） | **已有**（settle_committed_receipt） | 缺失（**盲重放**：非 0 退出码→新 session 原样重试至多 3 次、无幂等栅栏，v1.1 补；见 G3） | 待核 | 部分（P9 repeat_interval 未细核） | 待核（retry_tool 全包裹=重放语义声明缺位） |
| **跨进程写互斥（v1.1 新行）** | **已有（条件）**：_path_lock 在 _lock_root 下 on-disk fcntl（src/llm_loop/workspace/file_service.py:121-180），前提=争用双方共享同一 data_dir/lock_root（G2b）；另有 **run_lease**（src/llm_loop/core/session.py:660-670，`<sid>.run.lock` 跨进程非阻塞 fail-closed 防同会话双跑；v1.0 漏记机制，v1.1 补） | 缺失 | **已有**（Web 进程自带完整引擎，human 与模型编辑共享同一 FileService/锁；G8 已关闭） | **已有（进程内）**：SubAgent 与主循环共享同一 registry 实例（src/llm_loop/factory.py:1380-1388） | 缺失（独立进程） | 不适用 | 不适用 | 不适用（远端） |
| 统一查询 | **已有**（FileEffectQueryService 投影 TOOL/HUMAN 两族事件；search_records kind=file_effect） | 缺失（无事件可投影） | **已有** | **已有**（同投影） | 缺失 | — | 部分（search_records 各 kind） | 部分（工具自述远端状态查询〔未核〕） |
| 隐私导出 | 部分（artifact 不可变已有；导出脱敏**验收未定义**） | 已有（env scrub；输出进 evidence） | 部分 | 部分 | 已有（_redact） | 待核 | 待核 | 待核 |

## 4. P1–P4 已覆盖扣除（R01/R02 剩余面）

已由现有链路覆盖（不再列入待修）：
- edit_file/human 路径的 R01：prepared 先于写且必须持久（写前 fail-closed），崩溃窗口=prepared-only，可对账恢复；observed 失败如实标 recording_failed 不吞。
- edit_file/human 路径的 R02：版本前置+锁内基线字节复读（第三方同尺寸同 mtime 写也不放过）。P4 已证 stale write 拒绝、人工修改保留〔用户核证〕。
- 已完成写不重放：P4 已证（AI_MARKER 计数==1）；引擎重建走 file_effect_query 回执而非伪造消息〔用户核证+测试断言〕。

**R01 剩余** = P2/P3（shell 副作用无 prepared→observed）、P7（dsh 对 cwd 写入 + 失败盲重放至多 3 次，v1.1 补）、P8（发送确认后崩溃窗口，待核）、P11（codearts_dispatch 崩溃后仅凭远端查询对账，本地无 WAL 记录〔未核〕，v1.1 补）。
**R02 剩余** = P2/P7 可静默覆盖版本化文件（不共享 _path_lock、无基线复读）。human↔model 并发写**不在剩余面内**（v1.1 关闭 G8：Web 进程自带完整引擎，human 编辑与模型编辑共享同一 FileService/锁）；真正的跨进程面是并行 CLI loop 作为第二进程——互斥前提=共享同一 data_dir/lock_root（G2b），另有 run_lease 防同会话双跑。

## 5. 真实缺口（按事实损坏风险排序）

- **G1（最高）shell 可写任意可达路径，无版本/锁/回执**（v1.1 改写口径，A2）：workdir 仅校验"有效目录"、缺省才落 workspace_base()（src/llm_loop/tools/builtin/execute_command.py:136-152）——实际写面是机器全域可达路径，非仅工作区。修复方向（先声明后实现）：副作用工具闭集内为 execute_command 增加"写外泄面"声明+审计位，**审计位必须覆盖工作区外路径（工作区外写盘只剩 job/audit 记录可查，无任何版本兜底）**；对已知版本化路径（artifact store 登记过的）写前告警/快照基线；不做命令语义解析。
- **G2 并发验证缺口（v1.1 拆分，A4）**：锁是单进程真理——进程内互斥依赖共享同一 registry 实例（SubAgent 已证：src/llm_loop/factory.py:1380-1388），跨进程互斥依赖争用双方共享同一 data_dir/lock_root（镜像检出正是各配各 data_dir 的风险场景）。拆为 **G2a**（进程内 fault-injection：spawn_subagent 与主循环并发 edit 同一路径；human↔model 并发写同理，G8 关闭后同进程假设已成立）与 **G2b**（跨进程前提确认：并行 CLI loop 与 Web/loop 是否共享同一 lock_root；若否，互斥只剩基线字节复读兜底，且存在残留 re-read→os.replace 写窗口）。
- **G3 dsh cwd 重叠与盲重放（v1.1 扩充，A3）**：cwd 指向本工作区时成为绕过路径（原缺口）；**补重放面**——非 0 退出码触发新 session 原样重试至多 3 次、无幂等栅栏，部分执行后失败的任务会被重复执行到同一 cwd；后台模式连 audit 也不做（src/llm_loop/tools/builtin/dsh_task.py:15,41,158-159,215-216）。最低成本处置：cwd 重叠→结果中显式提示+audit 记录；retry 参数语义声明为"仅限模型自证幂等任务"或加任务级幂等标记；不建议禁止。
- **G4 恢复后模型协议采用不稳定**〔用户核证〕：契约层（恢复注入/规则/工具描述）问题，非机械层。机械能力（snapshot+expected_snapshot_ref+WAL）已具备。方向：恢复注入中显式重申写协议，配一条 P4 扩展验收（恢复后首个 edit 是否携带 expected_snapshot_ref）。
- **G5 outbound 幂等/回执细节**：feishu 发送 confirm 后崩溃；codearts 族=P6（workflow 步执行器，未核）+ **P11（模型直达 dispatch，v1.1 新增）**——P11 远端五态回执与本地 WAL 对账均未核（本地对账目前缺位）。
- **G6 隐私导出验收未定义**：回执/evidence 导出前去除凭证、本机路径、原始轨迹的验收场景缺失。
- **G7 验收矩阵三缺**（承接复核意见）：预算耗尽→续做场景；**误报冲突率**（乐观锁摩擦度量，防止"反复等待确认"违反 §8）；导出脱敏场景。
- **G8 Web 进程模型（v1.1 关闭，A5）**：build_app 直接 build_engine(settings) 且单实例复用（`src/llm_loop/web/__init__.py:122-137`）——Web 进程自带完整引擎，human 编辑与该引擎的模型编辑共享同一 FileService；同进程假设成立，原待核项关闭。衍生项移交 G2b（并行 CLI loop 第二进程前提）；v1.0 漏记机制 run_lease 已补入 §3 跨进程行。

## 6. 不应实现（维持并扩充）

- **N1** canonical event store / 第二运行时事实源：docs/continuity.md 已声明 private continuity store 仅是跨环境 handoff transport；LoopX 借鉴止步于让既有事件/Task 存储满足不变量（稳定 ID、追加序、幂等、fail-closed、投影版本），**docs/*.md 是面向人的交付物，不降格为投影**。
- **N2** 通用操作 ID/幂等框架：shell 命令语义不可归一化。改为：枚举副作用工具闭集（本文 §2 即初始闭集），逐个声明式说明重试语义。
- **N3** 禁止 shell 或将其全量收敛进 FileService：shell 的价值恰在任意命令；正确路径是外泄面声明+审计位+对版本化路径的写前告警（G1 方向）。
- **N4** 自动重试 unknown 副作用：建议书 §8 已定，维持。

## 7. 对建议书 v2 的导出映射

| 建议书章节 | 由本审计导出的修订 |
|---|---|
| §2 能力矩阵 | 直接引用 §2/§3 表；四态标记法沿用 |
| §3.1 预算 | 补 G7"预算耗尽→续做"验收场景 |
| §3.3 租约/代际 | 降级：subagent 已有 generation steering 与 durable settle 回执；剩余项=G2a 验证 + G2b 跨进程前提确认（G8 已关闭） |
| §3.4 防重表 | N2 替换通用框架：以 §2 闭集为准逐工具声明（闭集 v1.1 补 P11；retry 语义声明补 G3 dsh、P11） |
| §4.1 事件顺序 | 加反误读条款：投影仅指事件投影；docs/*.md 不降格（N1） |
| §5 Phase B 优先序 | 重排为 G1 > G2a/G2b > G4 > G5 > G3 > G6；G8 已关闭，不再是前置项（v1.1） |
| §6 连续性检查 | P1–P4 链路已核，从待查项移入已覆盖扣除（§4） |
| 验收矩阵 | 补 G7 三场景；M02"折叠"需先固定触发协议才可测 |

## 8. 证据清单与未核对项

源码证据（v1.1 统一补 `src/llm_loop/` 前缀；file:line 见 §2/§3 表）：workspace/file_service.py（edit 全序列+on-disk 锁）、tools/builtin/edit_file.py:100-195（sink 绑定+symlink 防护）、core/tool_execution_journal.py:31-105（WAL 契约+批内 binding）、subagent/runner.py:73-215（journal/topology/delivery/settle/generation）、workspace/human_file_ops.py:24-26、workspace/file_effect_query.py（PREPARED/OBSERVED/REJECTED 投影+prepared-only 对账）、factory.py:649/662/789（FileService 单例共享）+1380-1388（SubAgentRunner registry 共享）+1490-1493/1533-1536/1556-1569（codearts 导入/直注册/审批回调）、tools/builtin/execute_command.py:95-125,136-152,192-196（JobRegistry+workdir 校验+超限先 killpg 整树再拒绝，无 false-success）、tools/builtin/dsh_task.py:1-11,15,41,158-159,215-216（脱敏+audit fail-open+盲重放）、tools/builtin/schedule.py:66-217（ScheduleStore）、events.py:850-920（主循环 WAL）、core/session.py:660-670（run_lease）、web/__init__.py:122-137（build_app 单实例复用）、tests/integration/test_human_ai_continuity_p4.py:0-191（P4 断言）。

未核对（如实声明）：workflow codearts 内部实现（P6）；P11 codearts_dispatch/cancel 的远端五态回执细节与本地对账缺位；feishu 发送幂等细节；P10 各记录面工具逐项幂等语义；跨进程 data_dir/lock_root 一致性与 run_lease/on-disk 锁的实际互斥行为（G2b）；未运行任何 fault-injection（G2a 结论为"机制已有、验证缺失"而非"已验证"）。Web 同进程问题已关闭（G8，v1.1：build_app 自带完整引擎）。
