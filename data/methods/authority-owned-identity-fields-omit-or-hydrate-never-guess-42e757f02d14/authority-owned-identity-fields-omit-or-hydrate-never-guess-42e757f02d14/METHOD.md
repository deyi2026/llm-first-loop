---
method_id: authority-owned-identity-fields-omit-or-hydrate-never-guess-42e757f02d14
name: authority-owned-identity-fields-omit-or-hydrate-never-guess
description: 登记/账本/结算类写入（create_goal、lane_open、知识结算等）中的身份与绑定字段（session_id、owner、record ref）由权威方持有：凡本 run 回执没有逐字给出该值，就不要凭上下文构造填入。可自绑定的字段直接省略让运行时绑定；被拒提示『与可信绑定不一致/未知引用』时，改为省略重试或从权威回执逐字水合，绝不迭代候选值。边界：跨会话必须显式引用他人 id 时只能从共享账本抄精确值；命名缺失字段的校验错误则按合同差分补值而非省略。
aliases: 不要猜会话ID, session_id与可信绑定不一致, create_goal被会话归属拒绝, 登记时身份参数留空让运行时绑, 引用字段照抄回执别手拼, 猜ID被拒后别换值重试
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5a331d35-335d-4ca3-9a84-cf13f694d86c:1:b521bb1d48cf6168340d
evidence_refs: learning:learn:74bbe800621b
created_at: 2026-11-16T01:26:20.846645+08:00
updated_at: 2026-11-16T01:26:20.846645+08:00
---
## Trigger
向登记/账本/结算类写入工具传参时，出现身份或绑定类字段（session_id、owner、record/method ref），而手头没有任何回执逐字给出其权威值；或已收到『与运行时可信绑定不一致/未知引用』类拒绝

## Discriminator
该字段的权威值由绑定权威（运行时或权威账本）持有：要么本 run 回执已逐字打印该值（可照抄），要么工具可自绑定（可省略）；两者皆无而仍想构造，即判定为猜测。首次拒绝回执中『session_id 与运行时可信绑定不一致』的原文就是该字段属权威持有的直接证据

## Short path
- 调用登记类工具前逐字段自检：身份/绑定字段若无回执逐字给出权威值且工具可自绑定，直接不传该参数
- 收到『与可信绑定不一致/会话归属拒绝』时，一次省略该参数重试；禁止枚举候选值或换措辞再猜
- 若省略后被判必填缺失：从权威账本/检索回执查到精确值并逐字复制，仍不手拼
- 成功后核对回执中 owner/session/ref 与运行时绑定或回执原文一致，确认无猜测字面量落盘

## Stop conditions
- 登记/结算成功且回执身份与运行时自绑定或权威回执原文一致
- 权威值经账本/回执检索证明确实不可得：停止尝试，向所有者呈报并请示，不以猜测收尾

## Verification
- 最终回执的 owner/session/ref 来自运行时绑定或逐字抄录，而非本次传入的构造字面量
- 对持久化产物做一次字面量检索，确认无猜测生成的 id/ref 残留

## Counterexamples
- 跨会话显式引用他人资源（如指向其他 session 的 parent_goal_id）：省略无效，必须从共享账本抄精确 id，猜测与省略都错
- 拒绝原因是命名缺失字段且无可信绑定时：按合同差分补值而非省略（属 rejection-reason-as-contract-diff 卡范围）
- 调用方声明的标识（任务文本给出的 goal 标题、branch/worktree 名）是 caller-owned 事实，须逐字照传，不能省略或改写
