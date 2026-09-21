---
method_id: claim-by-claim-authoritative-state-audit-6785f55f3b95
name: claim-by-claim-authoritative-state-audit
description: 核验多声明交付报告时，先把每条声明绑定到唯一权威可观测源：运行中服务终态（live git_head / restart_required）裁定『已重启/已排队』，实时模型目录裁定『选择器可见/已入册』，git 裁定提交存在，项目 .venv 测试裁定代码可用。权威源一旦给出裁定即标记该声明已定，不再用全仓 search_files、空查询事件流等更宽路径重复佐证；仅当权威源不可得或可能是派生缓存时，才补一次落盘源核对。跑测试先用项目 venv 解释器，避免系统 python 缺依赖造成的假失败。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16fe103b-bd92-4cdd-984a-f6cd5b45235c:1232:42e317c184b6dd64ee4b
evidence_refs: learning:learn:22f7814076fe
created_at: 2026-09-20T17:24:10.361217+00:00
updated_at: 2026-09-20T17:24:10.361217+00:00
---
## Trigger
用户转述另一会话/第三方的多项交付声明（如『已上线/已入注册表/重启已排队/测试全绿』），需要逐条对账真伪时

## Discriminator
每条声明是否已有一个直接权威源回执给出裁定——例如服务终态里 live git_head 仍为旧提交且 restart_required=false，实时模型目录里目标模型缺席。存在这种回执即该声明已定，此后任何进一步的仓内宽枚举都是 post-sufficiency 动作

## Short path
- 把声明列表拆成单条可证伪断言，逐条标注其唯一权威源（live 服务状态 / 实时模型目录 / git / 项目 venv 测试）
- 依次执行这些权威查询，每条声明获得一个裁定（真/伪/不可证）
- 对已裁定的声明不再发起 search_files 全仓枚举或空 query 的事件流查询做佐证
- 仅当某声明的权威源不可得、或 live 视图可能是缓存/派生数据时，对该条补一次落盘源核对（如真实注册表文件）
- 测试一律用项目 .venv/bin/python 运行；全部声明有裁定后输出对账表并停止

## Stop conditions
- 每条声明都恰有一个权威源裁定，且不存在未绑定权威源的悬空未知量
- 若做了落盘交叉核对，live 源与落盘源结论一致
- 对账表中每行裁定都能指向一次具体权威查询回执

## Verification
- 复查动作序列：不存在对同一声明的第二次不同路径验证调用
- 测试结果来自项目 venv 且非收集错误（ImportError 类失败先换解释器再下结论）
- 『未发生』类裁定的依据是权威回执（live git_head / restart_required / 实时目录），而非搜索不命中

## Counterexamples
- 声明是历史时序性的（『X 时刻发生过重启』），live 状态只反映当前——此时事件流才是权威源，查询事件流不算冗余
- live 视图可能是缓存或派生数据且新鲜度未声明——对落盘源（如真实 providers.json）的一次交叉核对是必要的，不算重复
- 声明不涉及运行态、也没有 live 工具（纯静态代码/文档内容）——仓内搜索本身就是权威路径，此时不应跳过
