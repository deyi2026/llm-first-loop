---
method_id: exact-token-disambiguation-before-generic-platform-search-0770b3fc9a97
name: exact-token-disambiguation-before-generic-platform-search
description: 当需要在目标平台（如 GitHub）定位一个名字高度常见、同名实体众多的项目，而已获取证据（web 搜索结果、HF 链接、官方页面）中已出现更独特的标识 token（连字符精确全名、组织/账号 handle、官方域名片段）时：先用最独特的 token 在目标平台做精确查询，再用身份交叉边（平台 org/account token 与官方域名一致性）验证官方性；遇到 403 限流改走同源替代端点（raw 文件、HTML 页）并复用本会话已成功获取的证据，而不是重新宽搜或重抓同一 API。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:136:be5e004800e5c821f22f
evidence_refs: learning:learn:61a262caf5b0
created_at: 2026-09-18T10:40:19.069736+00:00
updated_at: 2026-09-18T10:40:19.069736+00:00
---
## Trigger
用户要求在目标平台定位并分析某个名称常见、易与无关同名项目混淆的项目，且当前已有证据中存在比通用名更独特的精确标识（精确全名、org handle、官方域名）。

## Discriminator
在首次 GitHub 查询之前，通用搜索结果已明示两个高区分度 token：HF 链接 'internlm/Atria-Dawn-Preview' 与官网域名 'api.atria-asi.ai'（隐含 org token 'atria-asi'）。这两个当时已知事实足以把候选从'平台上所有含 atria 的仓库（13 个）/同名用户（728 个）'缩到约一个可验证对象。

## Short path
- 通用 web 搜索消歧'atria'指什么（专业频道 0 结果即换 general）→ 未知量：项目本体与发布方是谁
- 从已见结果中提取最独特 token（全名 Atria-Dawn-Preview、org/域名 token atria-asi）→ 未知量：官方仓库在平台上叫什么
- GitHub API 用精确 token 查询（如 q=Atria-Dawn-Preview）→ 未知量：平台是否存在对应仓库
- 身份交叉验证：org token 与官方域名一致（atria-asi ↔ api.atria-asi.ai）→ 未知量：这是不是官方仓库
- 内容与元数据走已验证成功的端点（raw README、HTML 页；api.github.com 403 时切替代端点不重试）；元数据优先复用先前已成功的搜索证据 → 未知量：项目内容与质量
- 身份 + 内容 + 元数据齐备即停止发现，进入分析

## Stop conditions
- 已锁定唯一官方仓库（身份交叉验证通过）并取得其 README 与元数据，足以回答用户的分析需求
- 精确 token 查询为 0 结果且无其他独特 token 可提取——此时才回退泛化名宽搜索

## Verification
- 官方性：平台 org/account token 与权威外部来源（官网域名、HF org、官方公告）一致
- 去重性：引用的元数据来自本会话内已成功返回的证据（如先前 GitHub 搜索结果中的完整仓库字段），未重复抓取同一 API
- 完整性：README 被截断时已通过替代来源/分段读取补齐关键部分（评测表、部署节）再作结论

## Counterexamples
- 外部证据只给了模糊名（项目真就叫 'atria'，无全名/org/域名线索）→ 泛化名搜索是正确首步，本方法不适用
- 营销名与仓库名不一致且无链接线索，精确 token 查询 0 结果 → 需回退宽搜索并从结果中提取新 token
- 用户目标就是盘点/对比平台上所有同名项目 → 宽枚举本身是任务目标而非摩擦
- org handle 与官方域名无对应关系（自定命名）→ 域名交叉验证失效，需改用官方页外链等其他身份证据
