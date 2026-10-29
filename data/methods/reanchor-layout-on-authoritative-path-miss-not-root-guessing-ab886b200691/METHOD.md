---
method_id: reanchor-layout-on-authoritative-path-miss-not-root-guessing-ab886b200691
name: reanchor-layout-on-authoritative-path-miss-not-root-guessing
description: 把搜索命中展示的路径或文档裸文件名直接拼给精确读取工具、收到权威『路径不存在』回执后，禁止继续枚举其它根（绝对路径/主仓路径/同一相对路径重试）。此时唯一未知量是根映射与树布局（搜索索引根≠workdir、src 布局使包路径≠磁盘路径、存在镜像/快照目录）：用一次有界锚定探测（basename 限定的文件名搜索或 workdir 根单层枚举）重锚，从返回的同类路径样例（含快照样例）推导 live 候选路径，一次存在性探测确认后读取，并核对回执的 current_match/版本一致性标记。已被不存在回执登记的精确路径永久出列。
aliases: 搜索结果里的路径读不到文件, read_file 报路径不存在之后怎么办, python 模块名和实际文件位置对不上, 从快照路径推导 live 路径, 文档只给文件名没给目录, 路径读取失败后别再连着猜根
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:591:a8aba272d95fbf877197
evidence_refs: learning:learn:3ceb8614a25c
created_at: 2026-10-29T01:01:10.748664+08:00
updated_at: 2026-10-29T01:01:10.748664+08:00
---
## Trigger
从搜索工具命中的展示路径、或参考文档中的裸文件名（如『safety.py:24-49』）拼出的路径，被精确读取工具以确定性『路径不存在』回执拒绝；且该展示路径与当前 workdir 的根映射从未被验证过（仓库可能为 src 布局、搜索索引根≠shell workdir、存在 .releases 类镜像/快照目录）

## Discriminator
失败回执是权威 non-existence 而非 timeout/权限错误，且手头全部位置证据只是『展示路径或裸文件名』这类未验证文本——候选空间因此收缩为单一未知量『真实树布局/根映射』，而不是『多个可以挨个猜的根』；且已被登记不存在（TTL）的精确路径，重发不产生任何新信息。

## Short path
- 允许一次按展示/拼接路径的读取尝试；其失败回执本身就是第一份权威文件系统真值
- 收到权威不存在回执后立即停止拼新根：不再试绝对路径、主仓路径，更不重发同一相对路径（登记回执已显式建议停止）
- 做一次能回答布局问题的有界锚定探测：basename 限定的文件名搜索，或 workdir 根的单层完整枚举——不要只 ls -d 检验自己刚猜的那一个子路径
- 从探测返回的同类路径样例（如快照 .releases/*/src/... 中体现的布局）推导 live 候选路径，一次存在性探测确认
- 读取成功后核对回执一致性标记（current_match/非快照漂移），再进入内容分析

## Stop conditions
- 有界探测已产出唯一 live 路径并成功读取、且回执标记与当前树一致 → 定位结束，进入内容分析
- live 树无该 basename、仅快照命中 → 判定版本偏差或文档过期，查分支/问用户，不再枚举其它根
- 同一精确路径已收到不存在回执（或已被 TTL 登记）→ 该路径永久出列，禁止重发

## Verification
- 最终读取回执的路径前缀与推导样例的布局一致，且 workspace_path_state/current_match 类标记确认非快照漂移
- 用文件内符号证据（类名/import/行号注释）与上游文档引用交叉核对，确认是同一实现而非同名文件

## Counterexamples
- 失败属于权限/scope 绑定层（工具级 scope 错误码、EPERM 而非『不存在』）→ 走权限分层路由，布局重锚无效
- 文件刚被删除或目标分支未检出：布局探测找不到 live 候选时，正确动作是切分支/向用户求证，而非继续猜镜像或其它仓
- 仅 .releases 类快照命中时把快照内容当 live 真值 → 版本漂移风险，必须显式验证 current_match 后才能引用
- 搜索工具与读取工具的同根性已被此前回执证明：单次失败更可能是改名/移动，直接 basename 搜索即可，无需 pwd/ls 布局推断
