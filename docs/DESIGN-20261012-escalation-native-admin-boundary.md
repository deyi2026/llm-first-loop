# LFL 审批与 macOS 管理员权限：最小可用边界

**状态：内部审批存储安全修复可单独验收；macOS 原生特权入口尚未安装或获准启用。**

## 用户操作：没有管理员密码表单

1. 日常任务：登录 LFL Web 后正常发起任务，LFL 自主技术审核、返工、
   发布前 GO/NO-GO，不需要每轮人工批准。
2. 真正安装 /Library/LaunchDaemons、创建 OS 账号时：
   只在本机 macOS 系统认证界面确认一次（或可信本地 Terminal）。
3. LFL Web 绝不接收管理员密码，也不把密码放入工具参数、环境、
   模型上下文、HTTP 接口、审计日志或文件。审批 Schema 明确拒绝
   administrator_password 等未定义字段。

## 两个权限层，不可相互替代

- LFL EscalationStore：申请、Web 审批、等待、一次性令牌。
  只解除 CatastrophicGuard 那一道 LFL 内部硬阻断。
  不解除 EXEC_MODE、ManagedServiceMutationGuard、外层工具安全层
  和 macOS UID 权限。它不能把普通 UID 501 变成 root。
- macOS 系统授权：由系统或本地受信任安装器处理。
  只有 macOS 真正批准后才能安装 system LaunchDaemon。
  LFL Web 的 approved 字符串或模型决定都不是 root 授权。

## 最小实施

近期不新增特权 HTTP API。已有固定 SHA256、已审核的双 Agent
原生启动脚本，由可信 Mac 管理员在本机完成一次安装；启动后
立即验证真实进程、Socket 的内核 UID、具体会话、私钥归属和拒绝机制。
绝不改写被平台拦截的命令来绕过外层安全检查。

仅当未来确实需要常态化一键维护时，才制作独立签名的 Mac 原生
helper，按 Apple ServiceManagement / SMAppService 将 LaunchDaemon
注册并由管理员在系统设置里批准。只允许预先审核的动作：
signer_install、signer_start、signer_stop、signer_status。
固定 root-controlled 路径、审核版本、会话或实例标识；禁止
任意 command、任意 path、动态脚本和通用 root shell。
需要真实本地调用方身份校验、命令型 allowlist、幂等审计及撤销。

Apple 官方参考：
- https://developer.apple.com/documentation/servicemanagement/smappservice
- https://developer.apple.com/documentation/servicemanagement/smappservice/register%28%29
- https://developer.apple.com/documentation/security/authorization-services

## 本轮已实施的范围

- EscalationStore 记录、审计、锁文件使用 owner-only 0600。
- 旧 0644 token 文件读入前在原始打开描述符上校验并收紧权限；
  损坏、符号链接、不属于进程本人的文件一律 fail-closed。
- 新记录用随机文件名 + os.open(O_CREAT|O_EXCL|O_NOFOLLOW, 0600)
  + fsync + 原子 replace；
  消除临时文件以 0644 暴露批准令牌的窗口。
- Web 审批请求拒绝任何未声明字段，包括管理员密码。

以上只增加内部审批私密性，尚未获得系统特权，也不代表双 Agent
已生产部署。最终仍须独立服务真实运行、GLM Reviewer/Witness、
STOP、恢复和回滚通过后才能上线。
