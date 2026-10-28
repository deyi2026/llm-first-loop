---
method_id: exact-path-only-discovery-resolve-store-naming-scheme-escalate-on-opaque-da02954b84a1
name: exact-path-only-discovery-resolve-store-naming-scheme-escalate-on-opaque-ids
description: 只持有精确路径读取工具时，要在目录型持久化 store 中定位一条未给出文件名的记录，第一个未知量不是'哪个文件'而是'该 store 的寻址/命名方案'。先读声明该方案的设计文档/源码（docs 索引→存储设计文档→store 实现），而不是枚举候选文件名。若方案使用不可推导标识（UUID/随机 session_id）、无全局索引，且允许工具集无任何枚举能力，路径枚举在结构上不可能收敛——失败回执自带的'停止该路径搜索，改用搜索工具或向用户求证'就是判别信号：尽早如实上报结构性缺口，请求单一缺失事实（文件名/child_id）或枚举授权，而不是继续烧几十次确定性失败。
status: active
source_model: glm/glm-5.3
source_episode_refs: episode:37160f81-3228-41ab-8fe4-bdeefed80db4:1:e63459e83b1f565cb7bc
evidence_refs: learning:learn:6dcbb72bd843
created_at: 2026-10-19T12:25:31.658960+08:00
updated_at: 2026-10-19T12:27:32.234181+08:00
---
## Trigger
目标事实位于目录型持久化 store（如 data/event_logs/<session_id>.jsonl），用户给出目录/容器路径但未给具体文件名；允许工具集只含精确路径读取（read_file 类）与权威查询工具，明确无列目录/搜索能力

## Discriminator
每次路径失败的回执都是确定性'文件不存在+TTL 24h 登记'并明示建议'停止该路径搜索，改用 search_files 或向用户求证'；目录回执明示'是目录而非文件，请用目录工具'。这些当时已可见的回执证明未知量已从'路径对不对'变成'目录内命名方案+内容清单'，而精确路径探测无法回答后者；声明命名方案的设计文档（docs/INDEX.md→event_sourcing.md，写明文件名=UUID session_id、无全局索引）当时已可读

## Short path
- 最多一次探测用户字面路径（worktree 内 data/event_logs），回执登记不存在并建议换机制，不重复兄弟路径
- 探测主仓库 data/event_logs → 回执'是目录'，把未知量转为'目录内文件的命名方案'
- 读声明方案的权威文档/源码（docs/INDEX.md → event_sourcing.md → src/llm_loop/event_log/store.py），确认命名=<session_id>.jsonl、UUID、无索引
- 核对允许工具集：无枚举/搜索工具；read_evidence 无已存在引用即拒；review_admission(status) 对未知 child_id 确定性 DENIED 且不给清单
- 结论：精确路径发现对未知 UUID 不收敛 → 立即如实上报结构性缺口，请求文件名/child_id/枚举授权三选一，不再猜测
- 拿到 child_id 后按指令轮询 review_admission(action=status, child_id=同一值) 至终态并按契约报告

## Stop conditions
- 命名方案已由声明文档/源码确认为不可推导标识且无索引、允许工具又无枚举能力 → 停止一切路径猜测，进入上报/求助
- 用户补齐文件名、child_id 或枚举授权后 → 停止发现阶段，转入权威读取/轮询
- 权威工具回执已达终态 → 停止轮询并按报告契约输出确切字段

## Verification
- 命名方案结论必须引用声明文档/源码原文（存储格式节），不得用猜测命名的命中率代替
- 逐个确认允许工具的回执形态：read_file 对目录/通配确定性拒绝；read_evidence 无引用即拒；权威工具对未知 id 的确定性拒绝（DENIED）确实不返回任何清单
- 最终回答明确区分'事件尚未发生'与'当前工具无法发现'，并列出解锁所需的最小事实（三选一）

## Counterexamples
- store 命名确定可推导（日期、固定 slug、顺序 id）：少量定向探测合法且比读存储源码便宜，不应过早升级为上报
- 允许工具含目录列举/搜索能力：直接列目录回答'哪些文件存在'，无需推断命名方案
- 标识已到手（用户已给 child_id，或已有合法 evidence ref）：直接走权威工具轮询/读引用，跳过全部文件发现
- 记录本身在权威工具的固定注册表里：先读该工具实现定位注册表路径（locate-handler-first 路线），命名方案分析是次要路径
