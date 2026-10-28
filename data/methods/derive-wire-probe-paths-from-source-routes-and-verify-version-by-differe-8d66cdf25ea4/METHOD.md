---
method_id: derive-wire-probe-paths-from-source-routes-and-verify-version-by-differe-8d66cdf25ea4
name: derive-wire-probe-paths-from-source-routes-and-verify-version-by-differential
description: 验证自有代码库服务重启后新代码是否真在线上时，探活路径不要靠猜：先用一条 grep 从源码路由装饰器（APIRouter prefix + @router.get/post）拿真实端点再 curl。猜路径得到框架级 404 JSON（detail:Not Found）即『服务活着、路径不对』，应转源码定位而非继续换路径试。探针要选新旧版本应答不同的：/health 200 且自报构建 git_head 等于目标提交；本次新增路由在无鉴权/空 body 下应答 422/401 而旧版本是 404，该差异即新代码生效的判别证据。控制面快照（pid/live head/generation）与 wire 探针两通道一致即收口，不再追加探针。
aliases: 重启完了怎么在线上冒烟测试新接口, curl 打错路径返回404接下来怎么办, 怎么确认线上跑的是新提交不是旧进程, fastapi 返回 detail Not Found 是不是服务挂了, 用新路由的422证明发布生效, health自报版本号对不上目标commit
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:3823:3dacbe3fa6e1864e6206
evidence_refs: learning:learn:262273b2534e
created_at: 2026-10-25T23:24:11.443119+08:00
updated_at: 2026-10-25T23:24:11.443119+08:00
---
## Trigger
自有项目服务刚完成受管重启/发布，需要线上 wire 层核验新代码生效，而确切探活端点路径未知或仅凭记忆

## Discriminator
目标服务就是本会话一直在改的本地代码库的 app（源码可 grep），真实路径由路由装饰器唯一决定；且猜错路径返回的是框架级 404 JSON（服务存活、仅路径错），不是连接拒绝/超时

## Short path
- 控制面快照先收：逐服务 live git_head/generation/pid_alive 与目标提交一致（已有快照则直接用其中句柄）
- 用回执里的 pid 做 lsof 得监听端口，不猜端口
- 探活前先 grep 源码路由装饰器（APIRouter prefix、@router.get/post/websocket），一次拿到 /health 与本次新增路由的确切路径
- curl /health：200 且自报 build git_head == 目标提交 → 运行中进程即新代码
- curl 新增路由（无 key/空 body）：期望框架校验 422/401；旧版本此处是 404 → 差异即新版本在线证明
- 控制面快照与 wire 探针两通道一致即停止，不再追加探测

## Stop conditions
- 控制面快照逐服务 live git_head == 目标提交且 restart_required=false，同时 wire 探针自报版本一致、新增路由非 404
- 已确认监听端口进程与快照 pid 为同一进程

## Verification
- /health 自报 build.git_head 与目标提交逐字一致
- 新增路由应答为框架校验类（422/401）而非 404，且该路由在旧版本语义下不存在
- grep 路由前先确认本地源码 HEAD 与线上 live git_head 一致，路径推导才可信

## Counterexamples
- 第三方/无本地源码的服务：无法 grep 路由，只能试路径或查 /openapi.json 与文档，本方法不适用
- 运行进程由发布快照/镜像启动且可能与本地工作树不一致：路由 grep 必须对准进程实际启动的代码版本，否则路径推导漂移
- 问题只需确认进程在跑（pid_alive 已足）：再做 HTTP 探活属 post-sufficiency 动作
- 404 来自网关/代理统一屏蔽而非应用本身：应用源码 grep 解释不了，应查网关配置
