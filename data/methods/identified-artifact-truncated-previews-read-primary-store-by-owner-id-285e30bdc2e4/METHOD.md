---
method_id: identified-artifact-truncated-previews-read-primary-store-by-owner-id-285e30bdc2e4
name: identified-artifact-truncated-previews-read-primary-store-by-owner-id
description: 当指令引用上一会话产物（如『按建议执行』），且该产物已被识别——同一命名内容在多个来源预览中反复出现、属主 session_id 已在 trace 中可见——而各检索面返回的都是机制性截断的预览（片段以『…』结尾、字段中段断开、hydration complete=false 分页）时，停止继续换关键词或换发现工具枚举：同类查询只能返回同一产物的更多截断预览。改为以属主标识为键定位主存储（按 session_id 命名的会话日志），直接提取目标类型记录（如 message.appended 的收口报告）取全文，校验一致后立即转入指令要求的实际任务。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:2dced6b3-0f9c-4e26-8d39-bf4d2576b525:0:3b2cd81073f7fb6bffb9
evidence_refs: learning:learn:bf6847327506
created_at: 2026-10-11T17:40:48.140763+08:00
updated_at: 2026-10-11T17:40:48.140763+08:00
---
## Trigger
用户指令引用先前会话的产物/结论；首轮流读取后产物已可识别（标题/片段可见，属主 session_id 出现在 trace 行中），但聚合索引与流视图返回的均为截断预览。

## Discriminator
三事实同时在场：(1) 同一命名产物被多个独立预览命中→产物已识别，无需再发现；(2) 预览呈机制性截断（…结尾、字段中段断开、complete=false 分页）→截断是索引显示属性而非内容缺失；(3) 属主 session_id 全程可得→主存储路径可用该键定位。三者成立时继续关键词检索期望收益≈0，读属主主存储是唯一能给出全文的动作。

## Short path
- 首轮流读取时即记下属主 session_id 与产物名（哪份报告/建议）。
- 见到预览截断+分页标记即判定：全文在主存储、不在聚合索引，停止换词检索。
- 用 session_id 作为键定位主存储（如 find -name '*<session_id>*' 或会话日志目录），而非用内容关键词做全文搜索。
- 在主存储中按事件类型提取目标记录（message.appended/最终报告）取全文。
- 校验 session/ts 与预览片段连续后立即停止发现，转入指令要求的实际任务。

## Stop conditions
- 已取得识别产物的全文，且此前预览片段可在全文中逐字定位。
- 主存储不存在或不包含该记录时，才回退到更宽的内容发现。

## Verification
- 提取记录的 session_id 与时间戳和 trace 中属主一致。
- 此前见到的截断预览片段能在全文中逐字找到（同一产物连续性检查）。
- 全文中的建议/结论与用户指令语义对得上（『建议』指的就是该文）。

## Counterexamples
- 产物尚未识别（不知道哪个会话/哪份文件）：宽发现仍是正确第一步，本方法不适用。
- 某次命中已含完整目标正文（预览未截断）：直接读它并停止，无需主存储。
- hydration handle 显示 complete=true 或分页即可读全且正文完整：继续读同一权威源即可，不必转主存储。
- 属主标识缺失或歧义（多个候选会话）：先消歧元数据，不可凭空构造路径。
- 上一会话结论可能已被后续写者推翻：先按最新权威记录核对版本，再谈执行。
