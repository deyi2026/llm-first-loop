# Peer 渠道 T6 验收：应拦输入实测（2026-11-08）

配套脚本：`scripts/peer_acceptance.py`（**进仓库、可复跑**）。
设计真值源：`docs/DESIGN-20261107-deepin-remote-takeover-agent-interop.md` §9。
上一轮（T5）明确写着"测试绿只证明代码路径正确，不证明真实端口上的应拦行为"——本文是那一步的补测。

## 1. 测法与边界

测法：`peer_acceptance.py` 用 `subprocess` 起**真 uvicorn 子进程**（`scripts/peer_serve.py`），
绑 `127.0.0.1:<随机端口>`，用真 `link_secret` 签四头，全部请求走**真 HTTP**；
"是否偷偷执行了"以审计目录里的 `admitted` 记录数与产物文件数为观测，不靠被测进程自述。

复现：

```bash
.venv/bin/python scripts/peer_acceptance.py          # 29 条，FAIL=0 时退出码 0
.venv/bin/python scripts/peer_acceptance.py --only core --json /tmp/t6.json
```

**本文不证明**（避免读成"已全面验证"）：

- 没在 deepin 实机上跑（本机 macOS），显示协议路径只用 `--display-protocol` 声明值验证，**未接真 X11/Wayland**；
- 没有第二个真实节点，跨机时延/断网/半开连接未测；
- 没有 TLS/mTLS（P1 明确不做，见 U9）；
- 并发只到"两请求交错"级别，未做压力与长稳；
- 全量 pytest 结论另附（见 §5），本文件不替代它。

## 2. 结果（29 条：PASS 25 / FAIL 0 / NOT_APPLICABLE 4）

| 条目 | 应拦输入 | 实测结果 |
|---|---|---|
| T1a | 不带签名头 GET manifest | 401 `peer_bad_signature` |
| T1b | 错密钥签名 | 401 `peer_bad_signature` |
| T1c | 未知 `node_id` | 401 `peer_unknown_node` |
| T1d | 认证失败是否打点执行计数 | `admitted` 计数 0→1 只在首次成功准入后 +1，三次认证失败未增 |
| T2 | 同 nonce 重放（首发 200） | 第二次 401 `peer_replay_detected` |
| T3 | 时间戳偏移 3600s | 401 `peer_stale_signature` |
| T4 | `shell.exec` 不在 `allowed_kinds` | 200 `denied` / `policy_task_kind_not_allowed` |
| T5 | 超过 `max_tasks_total=3`（已用满 3） | 200 `denied` / `grant_exhausted`，`admitted` 不增 |
| T6a | 首次派单 `fs.read` | 200 `succeeded` + 1 个产物 |
| T6b | 同 `effect_id` 同参数重发 | 200 同 `task_id`，`admitted` 1→1（未重复执行） |
| T6c | 同 `effect_id` 不同参数 | 409 `idempotency_conflict` |
| T7 | 执行中 kill -9 → 重启 | 杀前状态 `running`；重启后 `failed` / `crashed`，`admitted` 1→1，产物 0 |
| T8 | 产物落盘后篡改再取 | 取用 403 `artifact_digest_mismatch`；回执转 `failed` / `artifact_digest_mismatch` |
| T9 | `display_protocol=wayland` 下 `desktop.focus_probe` | 200 `failed` / `unsupported_display_protocol` |
| T10 | `base_url` 带路径 / 带 query / 非 http(s) | 三种均 `peer_transport_unavailable`（控制端侧闸） |
| U1 | 租约过期 | 200 `denied` / `grant_expired`，未执行 |
| U3 | `fs.write`（在租约白名单、不在无人值守白名单） | 200 `denied` / `requires_supervised_execution` |
| U5 | 非幂等 `running` 记录 + 重启 | `unknown_outcome` / `crashed`（真实重启收敛；前提局限见 §3-U5） |
| U6 | `health=degraded` | manifest `health=degraded`；提交 200 `denied` / `executor_unhealthy`，未执行 |
| U8 | 租约已撤销后提交 | 200 `denied` / `grant_revoked`，未执行 |
| U10 | 审计目录不可写 | 200 `denied` / `audit_unavailable`，产物 0，`admitted` 不增 |
| U9 | `--host 0.0.0.0` 起明文服务 | 退出码 2，stderr「拒绝启动：…不是回环地址」 |

不适用（4 条，逐条给理由，不当通过计）：

- **U4** `blocked` 超 `deadline` → `blocked_timeout`：本切片没有 `blocked` 生产者（人工确认通道未落地），回收器无输入可造。
- **U7** L3 文字注入 → `policy_desktop_type_not_allowed`：本切片没有 `desktop.type` kind（注入类属 P2 监督通道）。
- **U9b** 伪造证书 / mTLS 拒绝连接：P1 不做 TLS，证书场景不存在；替代控制是"非回环明文拒启"（U9 实测 PASS）。
- **U8b** 已入队任务随撤销转 `cancelled`：本切片同步执行，不存在持久 `queued` 任务。

## 3. 实测中暴露并修掉的缺陷（8 条）

这些不是"顺手重构"，是**跑真请求才暴露**的问题，逐条给"原来的错"与"现在的行为"：

1. **manifest 播报没有 handler 的 kind**（原：`fs.write`/`desktop.*` 默认 `default_enabled=True` 就进 manifest，派单后在执行期才 `handler_missing`，额度和审计都已消耗）。
   现在：`EXECUTABLE_KINDS` 与 `default_enabled` 取交集，不变量 `advertised ⊆ executable`。
2. **`desktop.*` 无协议级拒绝**（原：Wayland 下也走 `handler_missing`，把"协议不支持"伪装成"执行失败"）。
   现在：非 `x11` 一律 `unsupported_display_protocol`；`x11` 但无 handler 才 `policy_task_kind_not_allowed`。
3. **审计写失败返回 500 而非拒绝**（原：`admission.write` 的 `OSError` 冒到 HTTP 层，既没执行也没给封闭原因）。
   现在：`audit_unavailable`，且拒绝优先于原拒绝原因（没有审计记录就说不清"为什么拒"）。
4. **准入路径的二次落盘冲突**（写测试时暴露：admission 失败后 `_deny` 又 `put_task` 一次，触发 submitted→submitted 非法转移，反而 500）。
   现在：`_deny(persist=...)` 明确区分"已落盘"与"未落盘"。
5. **水位两处真值**（原：manifest 把 `audit_watermark_pct` 夹到 50，`health()` 却按传入原值判；对端按 50 排期、节点按 1 拒绝）。
   现在：构造时夹一次（50..99），播报值与判定值同源。
6. **撤销租约被报成 `grant_not_found`**（原：`_select_grant` 只挑 active，撤销件被过滤 → 控制端分不清"没租约"和"被撤权"，会继续重试）。
   现在：存在撤销记录时给 `grant_revoked`。
7. **产物篡改后任务仍显示 succeeded**（原：`read` 只对本次取用报错，回执仍说成功；且终局不可改写，无法收敛）。
   现在：检测到 `artifact_digest_mismatch` 时把引用该 ref 的 `succeeded` 任务转 `failed`；
   状态机为此**只开一条窄边** `succeeded → failed`（`state.can_quarantine`，其它终局改写仍一律拒绝，有测试锁死）。
8. **重启后中间态永久悬挂**（原：没有任何恢复路径；`running` 记录会一直挂着，额度也不回滚）。
   现在：启动时 `recover_interrupted()`：`admitted`/`queued` → `failed/crashed`；`running` 幂等 → `failed/crashed`；
   `running` 非幂等 → `unknown_outcome`；**不自动重跑**。`peer_serve` 与主 app 挂载两处都调用。

U5 的前提局限（写清楚，不含糊）：P1 只有只读 kind，**造不出"已产生部分副作用"**。
U5 验证的是"非幂等记录 + 真实重启 → `unknown_outcome` 且不自动重试"这条判定规则；
副作用存在性本身未测，等 `fs.write`（T9）落地后必须重测。

## 4. 与设计的偏差（登记，不隐藏）

- 设计 §5.8.5 要求 `kind` 用 enum 由 `peer_list` 动态生成 schema；工具 schema 是静态的，
  当前是 `kind: string` + 派单前本地前置校验（`kind ∈ manifest.kinds`，fail-closed）。
  防护等价，但模型侧看不到 enum，需 registry 支持 per-session schema 刷新才能真正对齐。
- `manifest` 没有 `counters.executions_total`：执行次数以审计 `admitted` 记录数为观测（单一真值，不另起计数器）。
  若要让对端直读，是加 `manifest.counters` 的小改动，本轮未做（会动 schema）。
- `blocked` 状态、`desktop.type`、TLS 均不在 P1；对应 U4/U7/U9b 标 NOT_APPLICABLE 而非 PASS。

## 5. 状态口径

- 本文件只声明：**上文列出的 25 条在真实进程/端口/HMAC 下断言命中**。
- "闸已生效"仅对这些条目成立；U4/U7/U9b/U8b 与 U5 的副作用前提**未覆盖**。
- 独立审查（RULE-AI-28）：审查子代理 PASS（candidate `a41d58a9…`，scope=patch，9 条声明路径）。
  证据形态：`review_admission` 工具回执（`cached_pass: true`、child `subagent_559f0d7a837d`、scope=patch）；
  **落盘回执 `data/review_admission/subagent_559f0d7a837d-full_test.md` 缺失**（2026-11-08 复核 `ls` 无此文件），原因未查清。
  本条只声明"工具回执显示 PASS"，不声称有落盘文件。

## 6. 执行记录（2026-11-08）

| 项 | 结果 |
| --- | --- |
| 验收脚本 | `python scripts/peer_acceptance.py` → 29 条，PASS 25 / FAIL 0 / NOT_APPLICABLE 4，退出码 0 |
| 单元测试 | `pytest tests/peer -q` → 163 passed, 3 skipped |
| 全量测试 | `pytest -q` → **14120 passed, 159 skipped, 16 deselected, 3 xfailed**，912.55s，退出码 0 |
| 代码提交 | `01fd9b526`（验收脚本 + 8 处闸修复）、`bf45b3224`（guard(r9)：4 处守卫漂移 + 本地时区） |

全量首轮（`01fd9b526`）曾 exit=1，暴露 4 类**只跑 `tests/peer` 看不见**的问题，已修：

1. `peer/models.py` 用 `datetime.now(UTC)` 序列化，违反宿主本地时区契约（RULE-AI-26）→ `system_local_now()`，
   `iso()` 输出本地偏移，`utcnow` 全量更名 `now_local`（名实相符）。
2. `src/llm_loop/peer/` 未登记 `top_level_units.packages` → 登记 plane=Action。
3. `peer/store.py`、`peer/admission.py`、`peer_tools.py` 未登记持久化写入面 → 登记
   `peer_channel_state`(T2/partial) 与 `peer_artifact_delivery`(T1/observe)，rationale 写明"缺父目录 fsync"。
4. 函数红线：`config.py::load_settings` 369→376、`web/__init__.py::build_app` 146→150，
   按 `scripts/regen_function_size_baseline.py` 逐条抬高（红线条目可见）。

环境事实（不是代码问题，登记以免误判）：本轮验收在 **git worktree** 内跑，
worktree 原本没有 `.venv`，导致 `test_env_preflight` 的"实测版本"断言拿不到版本号而失败。
补 `.venv` 软链（`.gitignore` 已忽略，不入库）后转绿；主仓直接跑不受影响。

## 7. T8 合并审查发现与修复（2026-11-08）

按 `skills/merge-review-gate` 清单拆三份独立只读审查：A1（认证/存储/状态机）、
A2（fail-closed/执行器/policy/产物）、B（诚实性/测试面/分支卫生）。三者均未参与本分支产出。

### 7.1 已修复（提交 `058f07962`）

| 编号 | 发现 | 处置 |
| --- | --- | --- |
| A1-A4 | `PeerError` detail 拼接 `OSError`/`JSONDecodeError` 原文，把本地路径回给已认证对端（**可达**） | 改为只带异常类型名 |
| A1-A4 | `_path()` 非法 task_id 抛裸 `ValueError`；`from_dict` 的 `KeyError` 逃逸 → 500 面（当前不可达：task_id 全由服务端 `f"task_{uuid4().hex[:20]}"` 生成） | 收敛为 `PeerError`，不再依赖调用方 |
| A1-附 | `os.write` 未检返回值，短写留半截 JSON（会被 `count_admitted` 按"已准入"计入） | 改为循环写满 |

回归测试（两条，"回退修复即红"已实测）：`test_corrupt_admission_record_fails_closed_without_leaking_path`
（KeyError 分支）、`test_unreadable_admission_record_does_not_leak_path`（OSError/IsADirectoryError 分支；
把 detail 改回 `f"...{exc}"` 时该用例变红，失败输出直接打出绝对路径）。

### 7.2 审查 PASS 面（摘审查者原文证据）

- **A1**：闸1 认证的 canonical 覆盖 method + path（含 query）+ body sha256 + ts + nonce；300s 时间窗、
  600s nonce 重放窗（按 node 分桶 + 全局 LRU）、`hmac.compare_digest`、nonce 只在验签后落账 → PASS。
  `O_EXCL` 不可变准入；同载荷幂等、异载荷 `idempotency_conflict` → PASS。
  十态枚举与 `receipt.schema.json` `$defs.state.enum` 逐一相同、非法迁移被拒 → PASS。
- **A2**：manifest 只广播真有 handler 的 kind（黑盒探针 `manifest_kinds()` 只回 `fs.read`/`fs.list`，
  即使显式传 `shell.exec`）；`desktop.*` 在 wayland/none → `unsupported_display_protocol`、
  x11 → `handler_missing`，两路都拒。审计写失败走 `audit_unavailable` + `_deny(write_audit=False, persist=False)`：
  额度不消耗、工具不执行、返回 200+denied 而非 500。水位单一真值（`service.py:90` 归一、`:104-108` 判定、
  `:129` 播报同源）。产物篡改 → `artifact_digest_mismatch` + `quarantine_artifact` 把 succeeded 改写为 failed。
  恢复入口 `service.py:389-407`、撤销报 `grant_revoked`（422）→ 均 PASS。

### 7.3 未修改的已知残留（逐条记可达条件，不阻断合并）

| 编号 | 残留 | 可达条件 |
| --- | --- | --- |
| A1-A4 | `models.py` 的 `iso()`/`parse_ts()` 抛裸 `ValueError` | 存储记录被外部改坏（`expires_at` 畸形）才可达；`auth.py` 侧时间戳另有 4xx 映射 |
| A1-A3附 | `state.py:30` 注释称 denied 只能由准入产生，与迁移表允许 `admitted/queued → denied` 不一致 | 注释级，无行为影响 |
| A2-A5 | `desktop.*` 协议判定嵌在 `handler is None` 分支内 | 未来补 desktop handler 时会绕过；本切片行为正确 |
| A2-A8 | 篡改检测需有人 GET 产物才触发 | 不 GET 则 succeeded 回执不变 |
| A2-A9 | `recover_interrupted` 的启动调用点未核 | 需在 `scripts/peer_serve.py` / web 挂载处核验 |
| A2-附 | `audit` 只包 `OSError`；`_select_grant` 取最早过期，旧租约可能遮蔽新租约 | 多租约并存时 |

### 7.4 诚实性/卫生面（B）

- 分支卫生 PASS：`git status --porcelain` 空、`main..HEAD` 19 提交、`diff` 无 `experiences/`、`data/` 夹带。
- 基线 PASS：`main=ee339e74d` 为 `HEAD` 祖先，`--ff-only` 可行。
- guards baseline：`config.py::load_settings` 369→376、`web/__init__.py::build_app` 146→150 属**既有条目抬高**，
  非"只新增"。按 `scripts/regen_function_size_baseline.py` docstring，该口径是"EVO-20261025-e0bff8ee 批准的
  红线放宽，须 guard(r9) 提交可见"；`bf45b3224` 即该 guard(r9) 提交，§6 第 4 条已披露 → 不判违规，但记明性质。

