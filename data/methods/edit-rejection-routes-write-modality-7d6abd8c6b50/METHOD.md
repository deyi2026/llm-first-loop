---
method_id: edit-rejection-routes-write-modality-7d6abd8c6b50
name: edit-rejection-routes-write-modality
description: 文件修改类工具返回 precondition 类拒绝时，拒绝回执本身已指明未满足的前置条件：按拒绝类别切换写入方式，而不是同参数重试。空锚点且目标为新文件→整文件写入(heredoc)；快照/锚点无法验证→对目标区间新鲜读取并重新锚定后再编辑；写入后立即语法/diff 验证。用回执类别把『再试几种写法』缩成唯一能满足前置条件的路径，消除必然失败的重复调用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:847:99fb2b11495d19f8fb02
evidence_refs: learning:learn:947ac191ffbc
created_at: 2026-09-24T11:29:47.375103+00:00
updated_at: 2026-09-24T11:29:47.375103+00:00
---
## Trigger
对文件执行 edit/modify/patch 类操作时，工具回执为 precondition 类拒绝（如 'old_string 为空无法定位/插入请锚定相邻原文'、'snapshot 不属于当前工作区或无法完整验证'），而非权限、配额或内容冲突错误

## Discriminator
拒绝消息命中的具体未满足前置条件：『插入请锚定相邻原文』说明该路径上不存在可锚定原文（典型为目标新文件，edit 原语本身选错模态）；『snapshot 无法完整验证』说明缓存视图不可信，重试同一快照在因果上不可能通过校验

## Short path
- 收到 precondition 拒绝后先对回执分类，禁止对同一编辑做同参数重试
- 空锚点 + 目标文件不存在 → 改用整文件写入（heredoc/新建文件），随后立即做语法或编译级检查确认非空壳
- 快照/锚点失配 → 对目标区间做新鲜读取，选取唯一相邻原文重新锚定后再提交编辑
- 每次写入成功后用 diff/相关测试确认仅含预期变更，再进入下一处修改

## Stop conditions
- 工具回执为成功且 diff/语法检查确认写入内容正确
- 拒绝类别为权限/认证/配额/传输类（非 precondition 语义）——切换写入模态无效，转上报或等待

## Verification
- 新文件：写入后立即运行语法检查（如编译/parse），得到 'syntax OK' 类回执
- 既有文件：编辑后 diff 仅含预期变更，且相关既有测试保持全绿

## Counterexamples
- 既有大文件中 old_string 未命中源于内容漂移：不可整文件覆写（会清掉无关内容），必须新鲜读取后重新锚定
- 回执为一次性瞬态失败（超时/断连）且重试可成功时，单次原样重试比重读文件更便宜
- 权限不足或只读挂载导致的失败：任何写入模态切换都无效
