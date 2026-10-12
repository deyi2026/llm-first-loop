---
method_id: residual-classified-error-verify-live-config-then-documented-boundary-effc5e38b02c
name: residual-classified-error: verify-live-config-then-documented-boundary
description: 修复已部署但同分类错误复现时，先证明运行时确实带着新配置（env 覆盖/部署 head/默认值到参数的接线），再看残余失败是否落在源码注释已写明的设计边界（硬上限+投影裁剪）内；若在边界内则停止调参，转而验证修复真正承诺的不变量（干净分类报错+同 target 判死后可重连恢复）。附带判读规则：降级错误附带的 diag 载荷反映上一条成功请求，只有 mode 分类字段才描述失败本身。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:2489:7fa921d281bbe47d0d70
evidence_refs: learning:learn:428a9af79ce9
created_at: 2026-09-18T09:32:29.196705+00:00
updated_at: 2026-09-18T09:32:29.196705+00:00
---
## Trigger
为某个已机器分类的失败模式（如 timeout / frame_too_large / 1009）部署了配置级修复并重启后，复测仍出现同一 mode 的错误，面临『再次调参数』还是『换方向排查』的分支点。

## Discriminator
错误带有定义过语义的分类 mode（frame_too_large = 对端 1009 关闭 = 响应帧超过配置上限），且报错同时声明恢复机制（dropped session for same-target reconnect）；而 diag 的 resp_chars/elapsed 属于上一条成功请求，不能当作失败请求的证据。这两个当时已知事实把搜索空间缩到两个可验证未知量：运行时配置是否生效、失败是否在已文档化的设计边界内。

## Short path
- 只取错误的分类 mode、忽略 diag 数值；在源码查该 mode 的定义（分类函数/docstring），确定失败的确切传输条件——解决未知量：到底什么失败了。
- 读该 mode 指向的配置项（默认值、硬上限）及邻近注释，确认残余场景是否已被文档化为有意边界（如『超大树交给 node_cap 投影裁剪，不做无界帧缓冲』）——解决未知量：这是 bug 还是已知边界。
- 若修复本应改变该配置：验证运行中进程真的带着新值——env 探针无覆盖 + 部署 head/generation 匹配修复提交 + grep 默认值到实际参数的接线完整——解决未知量：配置是否 live。
- 配置 live 且失败落在文档化边界内 → 不再抬上限；改为验证修复的核心不变量：判死后同 target 上 navigate+观察立即恢复且数据 complete——解决未知量：修复承诺的行为是否成立。
- 不变量实证后停止排查，归档经验（含 diag 载荷属于上一成功请求的注意事项）。

## Stop conditions
- 运行时配置已证实生效（无 env 覆盖、head 匹配、接线完整）且失败与文档化设计边界一致 → 停止调参，转验证恢复不变量。
- 恢复不变量已实证：错误干净分类、同 target 重连生效、下一次 navigate+观察成功且 complete。
- 若发现 env 覆盖存在或部署 head 落后于修复提交 → 转向修部署，不进入代码层排查。

## Verification
- 部署回执的 git_head/generation 与修复提交一致；env 探针显示无覆盖；grep 证明默认值直达实际参数。
- 降级后同 target 立即 navigate+snapshot 成功且数据源 complete（如 dom+ax 双源）。
- diag 交叉核对：其 method/resp_chars/elapsed 对应上一条成功请求，而非失败请求。

## Counterexamples
- 分类语义无任何源码/文档定义 → 不能信任 mode，需先用原始传输证据（close code、raw log）复现确认后再排查。
- 失败不在任何文档化边界内（无硬上限/设计注释）→ 『接受边界』分支不适用，必须继续根因迭代。
- 配置 live 但观测载荷远低于上限仍报超限 → 可能是分类器误判，应检查分类逻辑本身而非接受 mode。
- 一次性 transient 网络错误、无稳定复现 → 先重跑确认可复现，再做配置取证。
