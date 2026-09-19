---
method_id: remote-truth-via-read-only-channel-when-mirror-stale-2d6e3cbf61f9
name: remote-truth-via-read-only-channel-when-mirror-stale
description: 当对共享远端的 push 被拒 non-fast-forward 且本地远端镜像(tracking ref)被证明陈旧时，先用最廉价、独立的只读通道（托管平台 API / raw 文件 URL）单往返取得远端真值：当前 tip、提交元数据、其引用的裁决文档，完成分叉定性。不要在重型同步通道(git fetch)上反复零信息轮询等待，也不要对着陈旧镜像做分叉分析下结论。仅当需要远端对象本体（合并/构建）时才让重型通道成为关键路径，并可将其降级为后台定时重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:010fcc8e-3ba8-4948-9ae5-66a30cc8ea6e:836:740f958e5f04f473747a
evidence_refs: learning:learn:1ca1662e0eb2
created_at: 2026-09-17T15:31:29.298468+00:00
updated_at: 2026-09-17T15:31:29.298468+00:00
---
## Trigger
git push 被拒 non-fast-forward，且 rev-parse 远端 tracking ref 返回的旧 SHA 与服务端拒绝事实并存（本地镜像被证明陈旧）；或已观察到远端 git 传输通道慢/闪断，同时存在可用的只读 HTTP 通道（平台 API、raw URL）

## Discriminator
push 回执中当时已并存两个事实：① non-FF 拒绝证明远端 tip 不是本地 main 的祖先（远端存在本地从未见过的提交）；② rev-parse lfl/main 给出旧 SHA 证明本地远端镜像陈旧——任何基于该镜像的 main..lfl/main 分析都是对旧镜子做的。这两点当时就足以把下一步从'等 fetch/重试 fetch/对旧镜像分析'缩成'用独立只读通道单往返拿远端当前真值'，不依赖任何后来才读到的信息。

## Short path
- 收到 non-FF 拒绝+tracking 旧 SHA：确认唯一未知量=远端当前 tip 指向什么；标记本地远端镜像为陈旧，禁止基于它下任何结论
- 用只读单往返通道（托管 API 的 branches/<default> 端点）拿远端 tip SHA、作者、时间、message
- 沿该 tip 的 provenance 继续只读：commit 元数据(diff 规模、parent 血统)→其引用的裁决/治理文档，直到分叉性质（谁、基于什么、裁剪了什么）明确
- 定性完成后汇报并保持写侧安全态（不强推、不盲并、部署不动）；把 fetch 降级为后台定时重试，仅在需要对象本体做三方合并时才成为关键路径

## Stop conditions
- 远端血统已由权威元数据（tip SHA + parent + 裁决文档）完整定性，且需用户裁决的事项已列出
- 只读通道同样失败（同网络路径不可达、无私读权限）——此时等待/重试重型通道才是正确动作，转入定时重试

## Verification
- 只读通道拿到的 tip SHA 与 commit 元数据（parent、tree、message）内部一致，且与 push 拒绝事实（远端 tip 非本地祖先）相容
- 网络恢复后 fetch 成功时，远端 tracking ref 应收敛为此前只读通道拿到的同一 SHA（事后可校验，但方法本身不依赖它）
- 最终结论中所有远端侧事实均有只读来源 URL/回执支撑，而非来自陈旧镜像

## Counterexamples
- 本地 tracking ref 是新鲜的（刚刚 fetch 成功）：镜像即真值，无需额外只读往返，直接分析并停止
- 远端无私读 HTTP 通道（仅 SSH/内网 git 可达，或 API 也需不可用的凭据）：只读通道不存在，等待并重试 fetch 是正确动作
- 任务需要远端对象本体（立即合并、checkout、构建）：仅元数据定性不足，fetch 在关键路径上，不能只用只读通道
- push 拒绝原因是权限/认证失败而非 non-FF：未知量是凭据与授权，不是远端 tip，本方法不适用
