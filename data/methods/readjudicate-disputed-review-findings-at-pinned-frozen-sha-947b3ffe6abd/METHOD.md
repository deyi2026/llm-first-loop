---
method_id: readjudicate-disputed-review-findings-at-pinned-frozen-sha-947b3ffe6abd
name: readjudicate-disputed-review-findings-at-pinned-frozen-sha
description: 评审结论被他人以具体反证（真实键名、实际代码行、精确行号）挑战时，既不因压力整体翻供，也不防御性坚持：先把每项争议发现拆成原子断言，再对任务钉死的冻结锚点逐条重取证——若当前 HEAD/worktree 与冻结 SHA 不一致，只读 git 对象（git show <SHA>:path、git grep <SHA>），绝不读工作树。逐断言裁决：全假→撤销并认错；部分假→保留发现但修正证据位置与严重度；全真→维持。取证一律用纯文本探针（grep/sed），不走管道直连解释器。
aliases: 评审发现被打脸怎么办, 父侧反证该不该认, HEAD 漂移后该审哪个 commit, 被质疑的审查项逐条复核, 冻结版本取证不读工作树
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c5ef796f-1083-475d-a81b-8eade5649df3:148:e2f9c7301152cd5e7237
evidence_refs: learning:learn:e166052a9edb
created_at: 2026-11-14T15:47:22.589870+08:00
updated_at: 2026-11-14T15:47:22.589870+08:00
---
## Trigger
上一轮评审的具体发现被他人以具体反证挑战（对方引用真实 JSON 键名、实际代码实现、精确文件行号），且任务钉死冻结 SHA 并约束只核验不修改；环境中存在多个 worktree/HEAD 可能与冻结 SHA 不一致

## Discriminator
首条坐标检查即可判明的事实：任务命名的冻结 SHA 经 git cat-file -t 确认存在，而当前 worktree HEAD 与之不符（漂移）→ 唯一权威取证面是冻结 git 对象；同时挑战文本自带可独立证伪的原子断言清单（字段存在性/字符串出现/某行代码形态），每条断言都能被一条最窄文本探针一边倒地裁决

## Short path
- 固定取证基线：git cat-file -t <冻结SHA> 确认存在；比对当前 HEAD/worktree，不等则全程只读 git 对象（git show <SHA>:path、git grep <literal> <SHA>），不碰任何工作树
- 把每项被挑战发现拆成原子断言：字段/键是否存在、字符串是否出现、指控行号处代码的实际形态
- 每断言一条纯文本最窄探针：键清单（锚定缩进的 grep）、字符串全树计数（git grep <SHA>）、行段复读（git show <SHA>:path | sed -n 'a,bp'）；不用管道直连解释器以免触发灾难守卫硬阻断
- 逐项裁决：断言全假→撤销并如实认错；部分假→保留发现但修正证据位置/范围并调整严重度；全真→维持并回显自己的反证
- 汇总输出：修订后发现计数、最终 PASS/REVISE 是否变化、冻结 SHA 是否不变；如实披露被守卫拦截的命令与替代路径；保持只读无写入

## Stop conditions
- 每个被挑战断言在冻结对象上已有一边倒的文本证据（零命中或精确命中，且键清单已穷尽非截断）
- 修订后的发现数量与最终裁决变化已明确给出，且全程未做任何写入/测试/推送

## Verification
- 撤销项：争议字段/字符串对冻结全树 git grep 零命中，且目标文件键清单已完整枚举（覆盖完整、非部分回执）
- 保留修正项：新证据行在同一冻结 SHA 复读一次成立，并与被证伪的旧证据（如分块读 vs 全量读）并排对照确认二者不混淆

## Counterexamples
- 挑战只有泛泛质疑、无具体反证：无可拆原子断言，应先回看自己原始证据链是否完整，而不是发起新一轮取证风暴
- 任务未钉冻结 SHA、审查对象就是活 worktree：直接读工作树即可，绕道 git 对象层反而增加摩擦
- 断言涉及运行时行为（内存峰值、并发、性能）：静态文本对读只能修正证据引用，不能终裁行为本身，应标注需实测或不可核验
- 证据确需真正的解析/计算（跨文件引用闭包、结构化 JSON 计算）：纯 grep/sed 不够，按守卫提示走落盘执行或提权流程，不要用文本工具硬拼
