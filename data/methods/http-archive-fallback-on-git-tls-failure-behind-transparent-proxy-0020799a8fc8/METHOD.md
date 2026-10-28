---
method_id: http-archive-fallback-on-git-tls-failure-behind-transparent-proxy-0020799a8fc8
name: http-archive-fallback-on-git-tls-failure-behind-transparent-proxy
description: git 等协议级客户端在 TLS 握手层失败（如 SSL_ERROR_SYSCALL），且环境已知处于透明代理/TUN（fake-ip）之下、或同一主机的 HTTPS 已被其它客户端证明可达时：不要枚举代理端口、解析 api JSON 或试分支名，直接切到同一资源的 HTTP 归档端点。GitHub 用 codeload/<owner>/<repo>/tar.gz/HEAD——HEAD 由服务端解析默认分支，一次消除『默认分支是什么』这个未知量；解压后 ls 实际根目录名（仓库改名后可不同于 URL 名），不假设 <repo>-<branch>。一次回退即替代『代理探测→api.github 内联解析→分支枚举→目录名假设失败』的四段试错，把多候选收敛为单个可验证下一跳。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d1e343a5-0eb5-4b62-b607-a8cd333ed256:312:5149127f38ec2acc235e
evidence_refs: learning:learn:b95b02fbd8ec
created_at: 2026-10-15T11:04:04.105122+08:00
updated_at: 2026-10-15T11:04:04.105122+08:00
---
## Trigger
git/ssh 等协议级客户端向代码托管主机传输时在 TLS 握手层失败（SSL_ERROR_SYSCALL 等传输错误，非 404/403/DNS），且当时已有证据表明该主机 HTTP(S) 层可达：工具回执标注透明代理/fake-ip 放行、先前对同一主机的 HTTPS fetch 已成功、或归档端点已返回 HTTP 状态码

## Discriminator
错误回执的类别是传输层握手失败而非资源不存在；同时已存在的可达性事实（本集：每次 web_fetch 回执均标注 Surge/Clash fake-ip 代理通道放行，且 github.com 页面 fetch 已成功）说明资源在 HTTP 层可达——失败被隔离在 git 自己的传输通道上，因此下一步应换通道而非修代理或猜引用名

## Short path
- 从失败回执先分类：TLS 握手失败 → 资源未被判定不存在，问题锁定在传输通道
- 直接请求 HTTP 等价物 codeload.github.com/<owner>/<repo>/tar.gz/HEAD；HEAD 由服务端解析默认分支，200 即得默认分支快照，404 才说明资源或引用真的不存在
- 解压到临时目录并 ls 实际根目录名，用真实目录名进入后续流程（不假设 <repo>-<branch>，仓库改名后归档根名可变）
- 校验 pyproject/README 等仓库预期文件在位后进入正常安装；仅当确需 git 历史/submodule 时才回头修 git 传输配置

## Stop conditions
- tarball 下载返回 200、解压成功且实际根目录已确认、仓库结构校验通过
- HTTP 归档端点同样不可达（连接拒绝/超时）：说明是网络层问题，转回代理/连通性诊断，通道回退无效

## Verification
- codeload 对 HEAD 引用返回 200 且 tar 可识别（排除 301 HTML 体 / Unrecognized archive format）
- 解压根目录包含 pyproject.toml、README 等仓库预期文件，根目录名以 ls 实测为准而非 URL 推导

## Counterexamples
- 需要 git 历史、submodule/LFS 对象或后续 push：快照 tarball 不满足需求，必须修 git 传输本身（如显式 http.proxy / 换镜像 remote）
- 仓库不存在或为私有：HEAD 同样 404/403，应重验 repo URL 与凭据，而不是枚举分支名
- 主机对 HTTP 客户端也完全不可达（如本集 7890 端口 000 的全不通场景）：归档回退救不了，网络层诊断才是正解
