---
method_id: catchall-unavailable-label-read-child-terminal-output-then-budget-arithm-23d844e1b280
name: catchall-unavailable-label-read-child-terminal-output-then-budget-arithmetic
description: 编排器把子代理失败包装成粗粒度兜底分类（如 *_unavailable）时，该词不是诊断而是桶标签：真因在被受理 child 的终态原文里。当受理成功已返回 child_id、失败毫秒级完成、跨多次重试确定复现、且同通道小材料曾 PASS 而大材料必死（材料相关而非时间相关）时，第一未知量不是'环境哪层坏了'而是'child 到底说了什么'。先 subagent_result(child_id) 读终态原文，再按原文恢复预算口径与材料体量做算术对比，最后修真实生效的配置源（优先级链 env > *.local > base，先验证权威源再改）并热载——而不是枚举模型目录/刷 registry/再空转重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1b498f1a-b510-4497-be53-2ae3460c91be:0:786a4c53b505ac0f2c73
evidence_refs: learning:learn:a845378fda40
created_at: 2026-10-21T01:18:59.895263+08:00
updated_at: 2026-10-21T01:18:59.895263+08:00
---
## Trigger
闸门/编排器受理子代理任务成功（回执含 child_id）后失败，错误字面量为兜底分类（*_unavailable 类，不含具体原因），且失败确定复现、随材料规模而非时间变化（同通道更小批次材料曾通过）

## Discriminator
当时在手的三件事：①受理回执含 child_id（child 已 spawn，终态可读）；②失败 dur≈35ms（spawn 后立即死，与'服务不可达'的超时/重试语义矛盾）；③开场 get_goal 即已知批次1（54KB）同通道 PASS、批次2（145KB）连续必败——材料相关+确定复现，已可排除瞬态基础设施抖动，而环境侧假设（模型目录、registry 缓存、默认路由）均不解释'小过大死'

## Short path
- 按交接恢复状态与准确受理参数后做一次 admission 探测，拿到 accepted=true + child_id
- 失败后不重读异常串、不查模型目录：立即 subagent_result(child_id) 读 child 终态原文，取得真实拒绝语（本例：上下文预检接近窗口、无 search_archive、拒绝静默截断）
- 按原文恢复预算公式 min(0.9×context, context−16K, max_input_tokens)×chars_per_token，与当前材料体量（tracked diff + untracked 逐文件）做不等式，并解释'为何上一批能过'——确认确定性预算死锁而非通道故障
- 修真实生效的配置源：先验证优先级链（env > providers.local.json > providers.json）中谁是权威源，改权威源并 refresh_config 热载，不重试旧通道
- 重发 admission 验证：失败时长恢复正常执行量级且产出真实 verdict，而非毫秒级复死

## Stop conditions
- child 原文与兜底分类一致（确为服务不可达/连接层错误）→ 停止本方法，转环境侧冻结+退避
- 受理阶段即失败、从未返回 child_id，或 child 终态不可读 → 无可 interrogate 对象，退回环境探测
- 预算算术显示材料在限内仍失败 → 死锁另有根因，本方法只解决'先读原文'一步，回到诊断

## Verification
- 修复后同一材料重发 admission，走完 accepted→正常时长→PASS/REVISE 全链，而非毫秒级失败
- 复算不等式：上批通过材料 < 旧预算 ≤ 本批失败材料（解释历史通过/失败分界），且新预算 > 本批材料
- 确认被修改的配置文件确实是优先级链中的生效源（另一份同名文件改动不生效即非权威）

## Counterexamples
- 回执字面量已是预算命名型（如 exceeds_<N>）：确定性合同直接重组材料即可，无需读 child 原文
- 无 child_id 且错误为连接拒绝/DNS/5xx：真环境故障，材料无辜，冻结+退避是正确对策
- 同体量材料间歇性通过（flaky）：瞬态抖动，重试/退避即可，材料算术无意义
- child 原文只是复述同一 unavailable 且无新增信息：读取未增加判别量，转环境侧探测
