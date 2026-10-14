---
method_id: contract-check-before-automation-channel-switch-4149c372219c
name: contract-check-before-automation-channel-switch
description: 当自动化任务已有一条绑定通道在确切目标上取得过成功回执（本集：CDP rebind→navigate→wait 均在 mp.weixin.qq.com 成功），不要为同一动作引入并行的沙箱化工具通道，除非先读其声明的契约（静态门控、goto 白名单、作用域）。本集先写 playwright_exec 脚本被 import 门控拒绝，事后读 Schema 才发现其 goto 白名单仅 feishu/localhost，目标域根本不在作用域内——整条分支本可避免。与 repo-api-discovery 不同：这里的关键判别不是查 API 签名，而是『已有可用通道使替代通道失去必要性』+『门控工具契约可先行证伪其适用性』。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:52de39d5-c559-4d5f-be79-cf20cb120cfa:259:3d3859a782f1b4e1ec0b
evidence_refs: learning:learn:e95110d76aa7
created_at: 2026-10-14T09:43:13.447154+08:00
updated_at: 2026-10-14T09:43:13.447154+08:00
---
## Trigger
多通道自动化环境（如已绑定的 CDP 语义操作通道 + 受白名单/门控约束的沙箱执行工具）中，需要对同一目标页面/系统执行动作，当前通道已在该目标上成功过，而正考虑改用另一并行工具时。

## Discriminator
两条当时已知事实：① 现有通道对同一目标域已有 success 回执（rebind/navigate/wait 均在目标域成功，且历史经验卡写明 CDP 9229 为该类任务的自动化通道），替代通道并无必要性；② 门控工具的 Schema 在调用前即可读取，其声明（禁止裸 import、goto 白名单不含目标域）会直接证伪『该通道可用于此目标』。

## Short path
- 明确下一步所需的唯一能力（如向编辑器 DOM 注入/粘贴内容），检查当前已绑定通道是否已在该目标上成功且具备该能力——是则在原通道继续，动作直接产生回执。
- 仅当能力缺失或原通道失败时，先读替代工具的 Schema/契约（门控、白名单、作用域），据此判定是否切换，而不是先写执行脚本。
- 若 Schema 显示目标不在其作用域内，立即放弃该分支，回到原通道或升级给用户，不为被证伪的通道编写任何脚本。
- 最终动作回执应来自最早已验证可用的通道，并与其目标域一致。

## Stop conditions
- 目标动作已在原通道取得成功回执；
- 或替代工具契约（白名单/门控）证伪其对该目标的适用性，立即终止该分支；
- 或两条通道均无法覆盖所需能力，转为向用户说明并请求人工/授权决策。

## Verification
- 同一目标的执行轨迹中不出现第二条通道的 gate 拒绝/白名单报错回执；
- 每次首次调用带门控/白名单的工具前，存在一次契约读取动作；
- 最终成功回执的通道与目标域一致，且该通道在更早步骤已有成功记录。

## Counterexamples
- 绑定通道确实缺少所需能力（如原生文件选择器上传、跨域面板操作）时，切换替代工具是正确的——但仍应契约先行，先读 Schema 再写脚本；
- 目标域本就在沙箱工具白名单内（如 feishu.cn/localhost）且尚无绑定通道，直接使用该工具即可，无需先建 CDP 通道；
- 纯 HTTP 可取的公开页面，任何浏览器通道都是过度升级，应先用 web_fetch 类轻量工具。
