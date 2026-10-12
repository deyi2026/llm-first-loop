---
method_id: ui-option-gap-trace-renderer-to-registry-3916eaa3b88d
name: ui-option-gap-trace-renderer-to-registry
description: 当用户报"UI 某选项选不了/缺失"而底层配置或 runtime 已确认该值有效时，症状被限定在 UI 渲染层。此时不要做全仓关键词搜索（只会命中 README/CHANGELOG/evals 等噪声），而应：先只在前端源码目录定位渲染该控件的组件，确认选项列表来自哪个数据字段；再沿该字段回溯到后端解析代码与权威数据文件（注意区分主配置与 local/override 文件）；最后对比数据文件中该 provider 下全部模型条目（含用户可能实际在用的兄弟变体），找出缺失该字段的条目，修复并只重启受影响服务。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16fe103b-bd92-4cdd-984a-f6cd5b45235c:46:6d4cbd8bcae3297922ed
evidence_refs: learning:learn:59a4111ba488
created_at: 2026-09-20T16:57:32.322748+00:00
updated_at: 2026-09-20T16:57:32.322748+00:00
---
## Trigger
用户报告界面（如 Web UI）上某个选项/档位无法选择或缺失，而已有状态查询显示底层 runtime/配置中该值已生效，且部署信息可定位前端代码目录（如 webui/）。

## Discriminator
进入任何搜索前已存在的事实组合：底层配置已正确（状态查询显示目标值已在 runtime 生效）+ 投诉被用户明确限定为"web 端选择控件"+ 部署信息给出前端代码目录。这三点把未知量从"全仓哪里有问题"缩为单一问题"UI 选项列表的数据源是什么"，可直接对前端源码做窄 grep，无需全仓枚举。

## Short path
- 用已有状态输出确认底层（runtime/config）该值已生效，把未知量缩为"UI 选项列表从哪来"。
- 仅在前端源码目录 grep 该选项关键词，读渲染控件源码，确认选项列表来自哪个 capability 字段（如 reasoning_efforts），即 UI 是数据驱动而非硬编码。
- 沿该字段 grep 后端解析代码，定位权威数据文件；注意区分主文件与 local/override 文件（providers.json vs providers.local.json），以解析代码实际加载者为准。
- 读取该 provider 下全部模型条目做对比（包括用户可能实际所在的兄弟变体，如 flash 版），不能只看部署状态里 model_ref 指向的那一条——本例根因恰在兄弟条目缺字段。
- 补齐缺失字段、备份、JSON 解析验证，只重启受影响服务（如 web），提示用户刷新页面验证选项出现。

## Stop conditions
- 已在权威数据文件中找到缺失/错误字段，且与 UI 组件渲染逻辑对上（如列表为空则不渲染任何按钮），即停止排查。
- 修复已写入并通过解析验证、受影响服务重启已受理，即停止动作，等待用户刷新确认。
- 不要在数据源条目确认正确前，先怀疑"进程加载了另一份 registry"这类运行时假设。

## Verification
- 用与后端相同的解析方式重新读取修改后的数据文件，确认目标条目字段完整、类型合法。
- 把数据条目与 UI 组件渲染条件逐一对照（字段为空/缺失时的渲染行为是否解释了用户症状）。
- 重启后由用户刷新页面确认选项实际出现，形成闭环。

## Counterexamples
- 选项在前端硬编码而非来自数据源：读组件这一步即可发现并直接改前端，不应去翻 registry——因此方法要求先读渲染组件再追数据源。
- 症状其实在 runtime 层（实际生效值就不对）：应直接查配置/环境变量加载链，本方法不适用。
- 权威数据文件中该条目本就正确：缺陷可能在文件合并/覆盖顺序或 API 传输层，方法的数据流追踪仍适用但修复位置不同。
- 用户实际使用的模型不属于该 provider：需先确认用户所在模型/服务，否则对比错对象。
