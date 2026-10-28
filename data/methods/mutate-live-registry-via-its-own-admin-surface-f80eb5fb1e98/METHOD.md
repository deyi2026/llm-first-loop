---
method_id: mutate-live-registry-via-its-own-admin-surface-f80eb5fb1e98
name: mutate-live-registry-via-its-own-admin-surface
description: 要删除/修改由运行中服务实时加载的注册表（模型/provider/插件清单）时，若目录回执本身来自活动进程（标注 runtime snapshot、显示会话级覆盖、条目带 loopback base_url），第一个未知量应是『该服务自带什么变更面（管理 API/管理工具）』，而不是『配置文件在磁盘哪里』。优先探测并使用服务自身的增删接口（通常带热重载与校验），磁盘配置只作只读核验；文件编辑是 API 不存在或不可用时的回退。破坏性删除前先抓取条目现值留证，删除后回到同一运行时面复测计数。本集若按此走，可跳过对缓存/镜像目录的全仓搜索与大部分源码考古。
aliases: 删模型先问运行中的服务要管理接口, 改注册表别翻磁盘配置文件, provider 增删走热重载接口, runtime snapshot 说明有活服务可写, 破坏性删除前先留条目备份
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:8c4a0f45-1c62-47b6-a42f-e75f6bb2027a:30:460076d2393e175f2585
evidence_refs: learning:learn:67069a3c1f9b
created_at: 2026-10-26T23:26:26.303454+08:00
updated_at: 2026-10-26T23:26:26.303454+08:00
---
## Trigger
需要删除/修改由运行中服务实时加载的注册表条目（provider、模型、插件等），且已能通过工具拿到该服务的实时目录快照：回执 kind=runtime_snapshot / 由工具注册类活动进程产出 / 含会话覆盖字段 / 条目显式带 loopback HTTP base_url

## Discriminator
目录回执的 provenance 是否表明它由活动进程产出（runtime snapshot、tool observation、会话覆盖、loopback base_url）而非静态文件读取。若是，该进程既是读权威也最可能提供写权威——先枚举它的管理面，再考虑磁盘配置；工作区里大量带日期的缓存/镜像目录命中（governance receipts、eval manifest、test 文件）本身即是『搜错了层』的信号

## Short path
- 用目录工具确认目标条目与精确计数（如 workbuddy 18 个模型、provider 共 5 个），回执留存
- 把下一个未知量定为『变更通道』：探测运行服务自带的增删面（本机回环管理 API 或工具注册表中的管理工具），而不是全仓搜 yaml/toml/关键词找配置文件
- 确认可变更后，先 GET 抓取待删条目完整现值留证（可恢复性），再执行删除；留意响应中的 restart_required / 热重载语义
- 回同一运行时面复测：目录工具重查目标条目为 0，管理 API 计数对照（如 5→4），并核验默认模型与回退链无被删引用
- 对『目录中已不存在』的目标：任务化归为其外部注册源的开关位；定位该源只需读声明加载方式的 loader（docstring 常写明模块名与配置键），若文件在写通道外，把确切的一行改动交给用户

## Stop conditions
- 所有用户点名条目已删除且在目录工具与管理 API 两处独立核验一致，或已化归为一条明确交给用户的精确改动
- 探测证明运行服务没有可写管理面（API 不存在/只读/缺凭据）→ 停止 API 路线，回退到 loader 定位磁盘配置 + 重启路径
- 磁盘权威文件 grep 与运行时计数出现不一致 → 先解释差异再继续，不叠加新的变更

## Verification
- 删除后重新调用同一目录工具：目标 provider/model 计数为 0
- 管理 API GET 计数、磁盘权威配置文件 grep 计数、目录工具计数三处一致
- 变更响应 restart_required=false 或重载已生效；当前会话模型与回退链不受影响
- 破坏性删除前已留存条目现值（回执/evidence ref 或完整 GET 响应）可支撑恢复

## Counterexamples
- 服务未运行、注册表只是进程启动时加载的静态文件：没有可探测的管理 API，正确路径是读 loader 定位文件后编辑并重启
- 管理 API 存在但只读或需要会话不具备的凭据：文件编辑成为主通道，API 仅用于核验
- 任务是理解/审计注册机制而非变更条目：应读 loader 与源码，管理 API 无关
- 目录快照来自共享/远端实例而用户点名要改的是本地文件：变更面必须对准用户指定的权威，而非回执来源
- 条目需按复杂 schema 新增且 API 校验不覆盖目标字段：仍需参照 loader/文件中现有条目作 schema 样板
