---
method_id: endpoint-blocked-pivot-to-identity-pinned-artifact-ec9fe655b7e9
name: endpoint-blocked-pivot-to-identity-pinned-artifact
description: 当 discovery/metadata 端点被端点级封锁（403/限流）且 UA/工具轮换已耗尽时，停止在同一 source class 上换参数重试；若本地已验证的权威记录已钉死目标对象身份（版本/id/资产名），直接用该身份走规范工件路线（版本 tag 直链/下载页）取对象，并以同源 checksum 做确定性校验后再进入下一步。把'再试第 N 组参数'的枚举，换成'身份已知的单跳直取 + 哈希验证'。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc07ea9d-6ab9-44b7-b385-65eea54960b6:406:811fb4b6761dcd82d233
evidence_refs: learning:learn:a5a2eae860f6
created_at: 2026-09-28T19:25:42.047365+08:00
updated_at: 2026-09-28T19:25:42.047365+08:00
---
## Trigger
需要获取某个外部发布工件，路径上先调用 discovery/metadata API；该端点对 UA 轮换与回退工具均返回端点级封锁（HTTP 403/rate-limit），而目标对象的身份（版本号、release id、资产命名）已被此前读过的、freshness=verified_current 的本地权威记录显式钉死。

## Discriminator
两个当时已知事实叠加：(1) 失败回执明确是 403 且 UA 轮换/回退工具均耗尽——这是端点被限流，不是 404 对象缺失；(2) 同会话先前已读的权威文档显式记录了 release 版本/id 与资产命名。二者把候选空间从'对同一 API 换第 N 组参数'缩到'用已钉死身份单跳直取工件'。

## Short path
- 在触碰外部端点前，先从已读权威记录提取目标对象的钉死身份（版本/release id/资产命名）；身份缺失则本方法不适用
- 工件请求被 403+轮换耗尽拒绝时，把回执读作'端点级封锁'而非'对象缺失'，立即停止在同一端点换 UA/换工具重试
- 用钉死身份构造规范工件直取路线（版本 tag 下载页/直链），只发目标请求；未知量：该版本工件是否可取
- 取得工件后以同源 checksum 做确定性校验；校验通过即停止发现，进入下游动作（校验/握手/使用）
- 直取路线也失败（404 或同样封锁）时才升级为宽发现（认证、等待限流窗口、镜像），并如实报告阻塞

## Stop conditions
- 工件 checksum 与权威 checksums 逐字一致 → 停止发现，进入下游动作
- 直链返回 404 → 钉死身份已失效，回到发现路径并标记本地记录过期
- 所有非该端点的直取路线同样被端点级封锁 → 不再重试任何同源端点，显式报告阻塞交决策

## Verification
- 确定性哈希校验：工件 sha256 与同源 checksums 文件逐字一致
- 一致性检查：实际取到的工件版本/来源与本地权威记录钉死的身份一致，防取错版本

## Counterexamples
- 端点返回 404（对象不存在）而非 403：身份可能已过期，绕过发现会取错或取不到，应重新发现并修正本地记录
- 本地无任何记录钉死对象身份、任务本意就是'查最新'：discovery API 是必需路径，应加认证或等待限流窗口，而不是绕开
- 任务是核对'latest 是否已变化'：结论必须来自权威 latest 源，用钉死的旧版本直链替代会给出陈旧断言
