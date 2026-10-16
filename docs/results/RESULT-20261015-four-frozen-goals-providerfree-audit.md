# 四个历史冻结实验 Goal：零Provider终态取证与归档建议

日期：2026-10-15；只读依据：MCP Console list_goals(unfinished, checkpoints)、当地已存在 Git commit/冻结 manifest、已知私有 archive 的目录清单、当前 service_control generation267。**本轮不发 Provider 请求，不写行、不重播、不声称无记录等于不存在。**

| 未关闭 Goal ID | 最后可证明的里程碑 | 结论／安全处置 |
| --- | --- | --- |
| **afed3502-c838-4d61-90a1-229bbfda8893** EEv2.3 | formal2 **16/36** 已有 durable PASS，第17行 e23_locate_scoped__A-current__r3 曾被 supervisor advance，但无可验 terminal。冻结 manifest Git 37e74c94b72d8a08c134ba98b2038f70e380cde4；无匹配当前worktree、未定位正式 final-result commit/指定私有archive目录。 | **UNFINISHED / IDENTITY EXPIRED**。首先只读找原row17 status/raw/root/进程身份和所有剩余回执；不把另一个Method side-task算作正式EEv2.3。若重做须独立申请fresh freeze，不能擅补17-36。 |
| **9d0bfe0d-245a-4e00-a0af-0fd8df99e435** Qwen可靠性/S2B | frozen十行 commit **dfe29db0e8dc7e471964edad6cf38a2e0ecbd6c3**，计划SHA d6e960f11cd61be4f82fb4e78d49007f88317f2e77c1af4fd9b6a1b5d31e40cb；最后已证 **zero-model preflight**，无 measured row 真实回执。Gen129 Web marker 401 不等于模型可靠性失败。 | **NOT MEASURED**；旧Qwen/llama PID1130、69 tool surface 已不具当代身份。先判项目当前是否仍需此实验，保全协议、不重播旧10行。 |
| **4bca31f8-fac4-46e4-81b4-949c9e7a3360** Execution Ledger S2 | 12行A/B protocol SHA 63ffeda52df0b25d261a02038630d7627ee8fce998794bea6bf777455f38978e。原S1 projector commit 7b2b17c49c724497522e1c4f3acfcfb5e29024c4；有前置实现/zero-model preflight，但未证明正式12行完成。当前main没有 S1 execution_ledger.py，也没有 S2 optional query。 | **NOT QUALIFIED**；同Goal中完成的网页版GPT side-task与S2目标不同。若仍有价值，需新建隔离候选/冻新Session/EventStore/ToolJournal/Provider工具面，仍是可选只读查询、不得强制注入或隐藏工具。 |
| **232d6582-6f32-406d-a9d2-18deb5917fd6** FCR P2 | 已实证 **6/16**，Row7 k02_method_static_negative__discovery-off__cold 仅见 START，无终态；v0.2 gen120 freeze Git **ab356e8ff2ba24008c4bfddc49c19d31653bbf66**，SHA6a494f6c20ec02f8db14fc3cc83b9f626634183c40256f7074ddbc2390109252。 | **UNFINISHED / CURRENTNESS EXPIRED**；当代生产gen267；先从旧身份只读取证Row7是否真正settled，再由owner决定封存或新冻结，不重跑老行。 |

四项均不能据历史 0 active runner 或缺某一目录就判定正式实验已结束；若保留旧实验，应保存raw/status/scorer/manifest完整哈希且恢复前先证实全局顺序、模型/Provider/wire/cache和每条行身份。

## 其他六条历史Goal的准确处置

- **89d3d1e2** Rule28 Host：后续 main 604592a + Web gen267已覆盖核心能力，旧独立分支本身没按原候选完成全部终态；建议记录后续新交付引用后标记 superseded，不能强写 complete。
- **0a6518f6** 架构：Rule31已入main，Learning删除会话 bug 原来仍未入main；本轮新的已审R9隔离行为提交 **e49e3e0** 只是代码资格，未合main/上线；广域架构目标仍未全部交付。
- **b514d1be** 科普推广：10/15 头条、知乎有真实投稿/发布回执；掘金 BLOCKED_BY_PLATFORM，属于持续任务，Active 正常。
- **229df345** Stabilizer v1.3：冻结顺序违约已封存于 Git **4ceff8a212a706d5080b38a701bd775b2a98550d**，不能宣称v1.3合格；全新v1.4有12行证据在 Git **9d77d766c7995ed8fd6af7426ed5d9f06e0fa6a6**。旧Goal建议 superseded。
- **f2f96791** Gen63：受管service action svc-089833385ea14a6dba085e65ffa4711d 的实际 **status=failed**，不能谎报旧Gen63全部验收成功；后续已到gen267，保留失败并标记历史被取代。
- **e8cfa6de** MCP Console Goal清理：产品缺少历史 exact-ID cancelled/superseded；Blocked 合理，绝不修改运行 SQLite 或伪造完成。

## 需要的 Goal lifecycle 安全原语

新增明确终态 cancelled / superseded，保留与 complete 不同的语义；仅允许有准确历史Goal ID、用户授权、expected_revision CAS、非空原因与继承Goal证据指针的精确幂等操作。每次变更必须 append-only receipt，旧 objective/checkpoints/budget 完整保留，不允许以任务标题/语义相似自动选择，不得改写 completed 目标。单测覆盖跨scope拒绝、双并发 CAS、重复幂等、历史查询/回收与后继引用；此能力应在 MCP Console 真实服务而不是无关 LFL introspection.goal 实现。

**本轮不修改任何一个历史Goal状态；没有安全 exact-ID supersede 工具前，不清空 Active，也不写活数据库。未来每项实验重启前都必须另行申请当代有效的冻结实验资格。**
