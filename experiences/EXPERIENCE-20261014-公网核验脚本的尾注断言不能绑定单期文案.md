---
title: 公网核验脚本的尾注断言不能绑定单期文案
scenario: 头条图文发布后的公网 DOM 核验脚本复用（verify_toutiao_public.py）
root_cause: ""
solution: "核验脚本的断言必须写成与本期尾注措辞无关的稳定标记（如\"资料来源与免责\"+\"不构成第三方独立评测\"），不要复制上一期的具体文案（如\"全部 9 张图片\"）；出现 PUBLIC_DOM_INCOMPLETE 时，先用一次只读 CDP evaluate 打印公网 body 片段确认内容是否真的缺失，再决定改文章还是改断言。"
evidence: "evidence://v1/19f65ab53c510fb78f76fe9185ebad576e93e29d1d16f86132ef399d1927a237"
tags: [头条发布, 公网核验, 断言设计]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-14T21:54:54.458906+08:00"
updated_at: "2026-10-14T21:54:54.458906+08:00"
---