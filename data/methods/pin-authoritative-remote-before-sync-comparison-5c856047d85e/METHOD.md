---
method_id: pin-authoritative-remote-before-sync-comparison-5c856047d85e
name: pin-authoritative-remote-before-sync-comparison
description: 仓库配置多个 remote 时,任何『本地 vs 远端』结论(ahead/behind、纯祖先、是否并错、是否需 push)都必须先钉死权威远端再比较。默认名 origin 不是权威信号;remote URL 中的身份线索(legacy/旧路径/不同 owner)才是当时即可用的判别事实。先列全部 remote、按 URL 判别权威基准,只对权威远端做比较,并在回复中显式写出『比较基准 = <remote>/<branch>』,把隐性假设变成用户一眼可纠正的显式事实。
status: active
source_model: glm/glm-5.3
source_episode_refs: episode:35effbfe-0312-45d2-a1bd-0418c1706ecd:584:26ecf39a4f335a72ed6e
evidence_refs: learning:learn:69cfa8a9722c
created_at: 2026-10-18T22:15:58.063227+08:00
updated_at: 2026-10-18T23:33:36.472762+08:00
---
## Trigger
需要给出本地分支与远端的同步/合并/推送状态结论(ahead/behind、祖先关系、是否需 push),且仓库可能配置了多个 git remote(或多个同类型端点:registry、集群、环境别名)

## Discriminator
git remote -v 输出中 remote 数量 >1,且某条 URL/仓库名含身份线索(如 legacy、旧路径、不同项目名);此时默认名(origin)不构成权威证据,身份词+近期 fetch/push 活动才指明当前工作基准

## Short path
- 做出任何本地↔远端比较结论前,先运行 git remote -v;未知量:有几个远端、各指向哪个仓库
- 若仅一个远端则无歧义直接比较;若多个,用 URL 身份词(legacy/新旧路径)与近期 fetch/push 活动确定权威远端;未知量:哪个是当前工作基准
- 只对已确认权威远端执行 fetch 后的 ahead/behind/祖先比较;未知量:真实同步状态
- 在回复中显式列出 remote→仓库映射表与所用比较基准 <remote>/<branch>,使用户可即时发现并纠正错误基准

## Stop conditions
- 比较基准已由 remote -v 输出钉死(remote 名+URL+分支),且所有同步结论均基于该基准
- 用户或流程明确指定比较远端时,以指定为准并照此声明

## Verification
- 回复中列出 remote→仓库映射与比较基准,任何 ahead/behind/祖先/push 结论都引用该基准
- 关系计算基于对权威远端 fetch 后的最新引用,而非陈旧 tracking 数据

## Counterexamples
- 仓库只有一个 origin,无歧义,直接比较即可,先做远端判别不产生信息增益
- 两个 remote 实为同一仓库的镜像或权限别名(URL 指向同一项目),名字差异不构成权威差别
- 用户明确要求与指定远端比较(即使其名字或 URL 含 legacy 字样)时,以指令为准
