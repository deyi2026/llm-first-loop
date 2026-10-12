---
method_id: authoritative-artifact-first-then-live-contract-probe-6867db304150
name: authoritative-artifact-first-then-live-contract-probe
description: 当被问“某注册表/配置条目是否有缺口需要修复”时：若权威 live 工件的位置已在前次会话或线索中确立，直接重读该文件取最新现状，跳过全库宽搜；与同类兄弟条目 diff 找缺失字段，grep 代码消费点定影响面；再按真实 client 契约（复刻 client 实际 payload 形状）做一次最小 live 探测裁决实际能力。明确拒绝型错误（如 400 且列出合法取值范围）视为“标志缺失即正确状态”的权威证据，不要好心补齐；正向多模态结论须用独立通道交叉验证（token 计量跳变 + 独立图像识别对照）防幻觉。只修被证实的缺口，写入后验证解析与选择路径生效。要点：记忆中的路径只当指针用，内容必须现读；路径失效（read 失败回执）即退回定向 search，不反复撞同一死路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:81:de4290ff57222f9078e0
evidence_refs: learning:learn:b73569acb722
created_at: 2026-09-18T10:33:07.958813+00:00
updated_at: 2026-09-18T10:33:07.958813+00:00
---
## Trigger
用户询问某注册表/配置中具体条目（能力标志、字段缺失类）“是否有缺口需要修复”，且权威 live 工件路径已在前次会话、注释或线索中确立；宽搜命中几乎全是归档/备份（.env.bak、evals/*/results）时尤应触发。

## Discriminator
当时已知：上一轮修改的就是 live 的 data/providers.json（同款缺口 flashx 即修于此），而 search_files 命中几乎全为 eval 归档与 .env 备份。该事实把“全库枚举定义”缩成“直接重读这一个已知权威文件取现行 flags”，且读到的内容天然是最新状态、无需再确认归档副本。

## Short path
- 直接重读已知权威工件（如 data/providers.json）中目标条目；未知量：两模型现行 flags 现状
- 与同库兄弟条目 diff（已修好的 flashx、deepseek-flash 均带 multimodal+note）；未知量：按本库规范到底缺什么
- grep 缺失 flag 的代码消费点（解析器+vision 选择逻辑+路由权重注释）；未知量：缺 flag 是否有功能后果
- 按 client.py 真实 payload 形状对每个模型做最小 live 探测：流式 include_usage / tools+tool_choice / 图片输入；未知量：实际行为是否与元数据一致
- 对结果定向裁决：正向图像结论用 token 计量差（1432 vs 基线 17）+ 独立图像工具描述对照做防幻觉交叉验证；明确拒绝（400/1210 列出合法取值 ['text']）视为权威负证据
- 只修被证实的缺口，写入后在解析器读出 True、显式 provider/model 选择从 None 变命中后停止；顺手确认 fallback 链第一跳可用即可，不扩展到未询问的模型

## Stop conditions
- 每个被询问条目的实际能力均已由 live 探测+交叉验证或权威拒绝错误定论，能逐条给出有证据的 yes/no
- 修复已写入且被解析/选择路径验证生效（读出 True、显式指定命中）
- 权威工件路径失效（read 失败且已登记不存在）时，仅做一次定向 search 重新定位，不重复撞死路径也不退回全库枚举

## Verification
- 注册表标志与实测行为一一对应：实测收图的条目有 multimodal:true；被 1210 拒绝的条目保持无标志，并在 note 写明勿补，防后人好心补错
- 图像正向结论具备两路独立证据：prompt_tokens 相对纯文本基线的显著跳变 + 独立图像识别工具对同一图片描述一致（防模型幻觉凑巧）
- 修复后动态读注册表的路径即时生效（无缓存依赖），显式指定从 None 变命中；未支持的模型显式指定仍正确返回 None
- 探测 payload 与 client.py 实际发送形状一致（stream_options/tools 条件发送/max_tokens），保证测的是真实契约而非简化版

## Counterexamples
- 首次接触的仓库、权威工件位置未知——此时适度的目录/内容发现是必要前置，不能跳过直接猜路径
- 问题纯读配置即可回答（如“默认模型是什么”），无需 live 探测——探测徒增调用并产生真实 API 费用与副作用
- 离线/无 key 环境或探测为写操作、计费敏感——live 契约探测不可行或不该做，退化为官方文档+错误码+兄弟条目对照
- 宽搜命中本身就直接指向权威文件（无归档噪声稀释）——此时先读完命中再决定是否缩小，不必另行定位
