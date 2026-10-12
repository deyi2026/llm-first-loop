---
method_id: diff-partition-revision-rereview-ff8f3977837d
name: diff-partition-revision-rereview
description: 复审修订稿时既不要全量重审（把未变内容重新枚举一遍），也不要只核对声明修复项就盖章（未验证继承）。正确动作：实测修订稿哈希绑定受审字节 → diff 修订稿与受审 baseline 得到完整 hunk 清单 → 逐 hunk 归因 → 每个 hunk 用当前最强可用证据独立验证（删除类声明 grep 目标关键词须零命中、含参考文献等次要位置；图像类做像素级转录而非只看文件存在；路径类逐一解析）。被引用但 diff 未触及的资产用字节同一性（同哈希/git 未修改）继承旧视觉核验；新增或变更的资产必须本轮重读。全部 hunk 归因且通过后才出整体结论。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:87454a3c-2a7c-4282-974a-24e435f8ebcb:58:79ce012e2ae83f3c4c22
evidence_refs: learning:learn:af4383bdd09d
created_at: 2026-10-11T01:35:58.630869+08:00
updated_at: 2026-10-11T01:35:58.630869+08:00
---
## Trigger
任务要求对一版声称已修复若干 REVISE 理由的修订稿复审并给出 PASS/REVISE，存在上一版已受审的 baseline 文件，且用户明示『不要假设旧审核自动有效』或同等回归检查要求。

## Discriminator
当时即可取用的窄化事实：baseline 与修订稿都已在手，二者的 diff 把『整篇文档都可能有问题』缩成少量 hunk。hunk 集合若能完全归因到『声明修复 + 机械性改动（如目录迁移导致的相对路径调整）』，其余逐字节未变部分即可继承旧审核结论，无需重审；无法归因的 hunk 才是本轮真正的新验证对象。

## Short path
- 实测修订稿哈希与来函声称一致（未知量：受审对象是否就是声称的那份字节）
- diff 修订稿 vs 受审 baseline（未知量：相对上轮到底改了什么）
- 逐 hunk 归因到声明修复或机械改动；无法归因的按新改动处理（未知量：哪些 hunk 需要本轮新证据）
- 按 hunk 类型用最强证据验证：删除类 grep 零命中、图像类像素级转录、路径类逐一解析存在（未知量：各修复是否真实落地）
- diff 未触及的引用资产以字节同一性继承旧核验，再出整体 PASS/REVISE（未知量：旧结论可否继承）

## Stop conditions
- 任一 hunk 无法归因且验证不通过，或某条声明修复在最强证据下不成立（关键词仍命中/像素仍含错字）→ 立即 REVISE 并列出该 hunk，停止扩大验证
- 全部 hunk 归因且验证通过、未变部分字节同一 → PASS，不再重读未变内容或重复核验已继承资产

## Verification
- 实测修订稿哈希与声称一致，把结论绑定到具体字节
- 删除类修复：对被删声明关键词（含变体写法与参考文献等次要出现位）grep 全文零命中
- 图像修复：像素级逐字转录确认目标文字，而非仅确认文件存在或尺寸变化
- 所有引用路径逐一解析到存在的文件；baseline 本身的身份用 git 状态或版本说明钉死，确保 diff 是对着上轮受审那版

## Counterexamples
- 首次评审、不存在已受审 baseline：没有 diff 基准，继承机制无从谈起，须全量审
- 修订是大幅重写、diff 覆盖大部分行：『未变即继承』的窗口塌缩，等同全新评审
- 修订只替换二进制资产、文本 diff 为空：diff 无信号，必须对每个资产做内容级核验
- baseline 身份不明（工作区里的旧文件可能不是上轮受审版本）：先钉死 baseline 再 diff，否则产生假继承
