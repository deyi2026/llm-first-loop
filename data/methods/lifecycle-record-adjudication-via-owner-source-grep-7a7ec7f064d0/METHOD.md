---
method_id: lifecycle-record-adjudication-via-owner-source-grep-7a7ec7f064d0
name: lifecycle-record-adjudication-via-owner-source-grep
description: 对系统管理的生命周期记录执行人工裁决/状态流转时，不按目录名或文档引用猜存储、不在多仓工作区全树扫描；先解析拥有该记录类型的系统安装根，再用记录类型字面量（store 文件名常量、ID 前缀、状态动词）做作用域受限的源码 grep，一次性读出存储路径、状态机合法迁移与官方变更入口（CLI/路由），随后按精确 ID 取全量记录、沿官方通道交付命令。同名的类型目录（如 data/evolution/）未经代码追踪验证一律视为诱饵。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0991556a-eab1-4a63-9113-ea54a5166bf4:245:2f7fc4c534b3d93eabe0
evidence_refs: learning:learn:3a4d43623f58
created_at: 2026-10-23T04:14:15.582917+08:00
updated_at: 2026-10-23T04:14:15.582917+08:00
---
## Trigger
用户要求对一条由系统自身结构化检索（search_records 类工具）命中的生命周期记录执行状态流转或人工裁决，需要给出可复制的官方操作命令；记录带稳定唯一 ID 与 status/requires_human/owner 等状态字段，但存储位置与合法流转入口未知；工作区含多个大型 checkout（宽扫描必超时）或存在与记录类型同名的目录。

## Discriminator
记录是经系统结构化检索返回的系统实体（非文件直读），且旁证文档显示其处于状态机中（如 status=executing 待 evolution_complete）→ 必有拥有者代码同时定义其存储路径常量、状态机与流转入口；工作区内按记录类型命名的目录（data/evolution/）与 docs 引用只是线索，未经代码验证不是真值源。

## Short path
- 记录检索命中后，第一未知量定为『哪个系统/安装根拥有该记录类型』：用工作区元数据（如 path_registry/运行配置）一步解析安装根，不做全树 find。
- 在拥有者 src/ 内对记录类型字面量做受限 grep（store 文件名常量、ID 前缀、状态动词），一次读出：存储路径常量、状态机合法迁移、官方变更入口（CLI 子命令/工具注册描述/web 路由）。
- 按代码给出的存储路径用精确 ID 一次 grep 取全量记录，核对当前 status、owner、requires_human 是否满足流转前置。
- 读流转入口实现，确认参数形态（位置参数 vs flag）与并发安全（flock、审计副作用），排除不能到达目标终态的通道（如 web review 仅支持 accepted/rejected）。
- 用只读官方命令（如 evolve-list）验证 CLI 能看到目标记录后，向用户交付写入命令＋验证命令，停止发现。

## Stop conditions
- 源码已给出存储路径与官方入口、全量记录核对通过、只读命令确认无 split-brain——停止发现并交付命令
- 确认记录系统为纯远端服务无本地源码——停止本路径转官方文档/API
- 记录当前状态不在目标流转的前驱集内——先解决前驱动作，不伪造终态

## Verification
- 最终命令引用的存储路径/入口与源码常量一致，且只读列表命令能看到目标记录（两处输出一致）
- 记录当前状态属于流转入口声明的合法前驱（如 accepted/executing→executed）
- 交付的写入命令走官方通道（带 flock/审计），未绕过状态机直改文件

## Counterexamples
- 记录系统是纯远端 SaaS/无本地源码→只能走其文档化 API/UI，本方法失效
- 需求只读且检索命中已完整未截断→无需定位 store，直接回答
- store 位置已被权威文档明确记载→读文档比 grep 源码更短
- 记录本身即用户可编辑文件（如带 front-matter 状态的笔记）→文件即真值，无代码通道可言
