# VERIFICATION-20261005 — Subject-Binding 可见性归因与验证证据落盘

执行: 2026-10-05 20:47–21:08（会话 abda90a9，Goal GOAL-20261005-3eaa9ace）
环境: web gen177（git 74dc50d79…，pid 34466），`runtime.toml` `method_subject_binding_experimental=true`（operator-owned）
对应建议: P0-1（归因+n≥10 矩阵）、P0-2（验证证据落盘）、P1-2（P0-2/P0-3 收口核实）、P2（附录）

---

## 1. 归因结论（P0-1）

**20:08:49 的 SUBJECT_BINDING_MISSING = qwen3.8-flash-next（cognilocal 本地弱模型）瞬态读判失败，
不是 schema 管线缺陷，也不是未重启 surface。**

证据链（按决定性排序）：

1. **同秒配对对照**：20:08:25 deepseek 臂 VISIBLE 与 20:08:26 qwen 臂 MISSING，两臂同 channel=web、
   同 tools_count=69、同一 gen177 进程，仅模型不同。
2. **payload 尺寸排除缺席**：配对两臂 `prepared.projected_bytes` = 36030 vs 36074，差 44B ≈ 模型名长度差；
   binding 文本（≥150B 紧凑态）若在任一臂缺席，差值不可能仅 44B。
3. **逐字复述坐实递送**：3/3 echo 探测中 qwen 将 description 尾部逐字复述，完整包含
   `lfl-method-applicability-subject-binding/v1`、`claim subject`、`experience/result/fixture`。
4. **当前态稳定**：今日 gen177 矩阵 qwen 臂 10/10 VISIBLE。
5. **历史现象真实**：post-fix（19:30 后）历史弱臂 4 次中 2 次 MISSING（50%），强臂 0/6——
   弱模型读取不稳定曾真实存在；19:20–19:23 的 4 次 MISSING 属 flag 生效前（两臂齐 MISSING）。

### 1.1 对既有结论的修正（诚实登记）

- 外部分析称"同 generation 重启后 Strong/Weak 都实际返回 VISIBLE"**不成立**：20:08:26 弱臂确曾 MISSING。
- 本轮执行中的两个中间判断已自我修正并沉淀：
  - "MISSING 来自未重启 surface"——不成立，两臂同为 channel=web；
  - "发现新 settle-loss 复发"——不成立，为孤儿扫描与在途 attempt 的竞态误报
    （lesson: EXPERIENCE-20261005-settle-loss-attempt）。

## 2. 可见性矩阵（gen177 web，n=10/臂，探测 prompt 与 19:xx 历史探测逐字相同）

| 臂 | n | VISIBLE | MISSING | 延迟(中位) |
|---|---|---|---|---|
| deepseek/deepseek-v4-flash | 10 | **10** | 0 | ~1.6s |
| cognilocal/qwen3.8-flash-next | 10 | **10** | 0 | ~7s |
| echo 尾部复述 (qwen) | 3 | 3/3 含全部字面片段 | — | 72–179s |

原始记录：`matrix_results.jsonl`（含每测 session_id、耗时、应答摘录）。
附注：echo 显示探测收到的是 ~151 字符**紧凑态**描述——binding 文本在工具描述压缩后完整保留，
这是 lazy schema 压缩路径有效性的直接证据。

## 3. 回归与 settlement（P0-2 落盘）

- **聚焦回归**：7 个相关测试文件（subject-binding flag / method learning / runtime resolver /
  lazy schema / subject refs / semantic method / method gate）→ **90 passed / 0 failed / 0.55s**。
  原外部声称"136/136"无任何落盘证据、不可复核；今日等价复测如实记录为 90/90（聚焦集定义不同）。
- **settlement 事实（今日 web 真实流量）**：22 个已完成探测会话 = opened 22（100% 带
  `prepared.payload_hmac` + `prepared.projected_bytes`）+ settled 22（100% success，0 失败）；
  加 echo/03 共 23 会话全部收口。
- **tools_fp 历史证据**：不可恢复（无落盘）。等价替代事实：配对会话 tools_count 相同、
  projected_bytes 差 44B、全部探测 settlement 成功。

## 4. P1-2 收口核实

| 项 | 文档状态 | 今日核实 |
|---|---|---|
| P0-3 Strict Durability | COMMITTED（10-02） | 静默期幂等复扫：candidates=0，already_orphaned=55（历史），**0 新增**。方法 caveat：扫描必须避开在途 attempt（见 §1.1） |
| P0-2 Provider Settlement | COMMITTED（10-02） | 残留仅 §6 "web 真实流量"断言条件式：chatgpt-web 全史 1 次（10-02 实现日自验，字段齐全），deepseek-web 0 次。无当日可推进项，维持条件式 |

修正：此前审查称"P0-2/P0-3 仍在途"不准确——两方案均已于 10-02 COMMITTED，残留为上述小项。

## 5. Artifacts（sha256 前 16 位）

- `matrix_results.jsonl` — bc302181cb6b6838
- `focused_regression_raw.txt` — 2161f279493a648b
- `orphan_rescan_dryrun.txt`（含竞态误报原样保留） — dfdf8ec4ec9f4134
- `orphan_rescan_quiet.txt`（静默期复扫，candidates=0） — 03ccaf1c4b156296
- `docs/SPEC-20261005-method-binding-efficacy-preregistration.md`（P1-1 预注册，冻结） — 61da4b1557a552e3

## 6. 附录：P2 横向任务集可行性（简评）

- **不建议现在建**：五家外部 harness 的证据深度是文档级，机械对齐判分需要对方侧注入结构化输出协议，
  不可控成本高；且当前最大缺口（Method 闭环效能）用预注册实验（见 SPEC）解决，性价比远高于横向对比。
- **最小可行方案（若未来要做）**：从本仓库真实任务历史抽 30 个可机械判分的任务（有 ground-truth
  artifact 的），只对比 2 家（Microsoft Agent Harness 与 OpenAI Agents SDK 的本地可跑版本），
  判分=artifact sha256 对照，不做主观维度打分。

## 7. 后续

- P1-1 预注册已冻结（§5 指针）；实验执行（C0 无 flag 进程建立、case 池构建、80 例跑批）为后续工作，
  判据不得事后修改。
