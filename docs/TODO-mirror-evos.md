# 镜像待办：演进项执行队列（2026-08-20 操作者整理）

> 来源: 主区 accepted 演进项账目核对（evolution_suggestions.jsonl）。
> 执行原则: 涉及 LFL 自身代码 → 本镜像验证 → 审批 → 推主区。

## 🔴 高优先（用户已批列入）

### E1. d8a76517 MemoryStore 外部进程直写覆盖风险 ✅ 已完成（镜像 2026-08-20）
- **修复**: `_save()` 写前 `_merge_remote_changes()`（磁盘独有条目并入内存, 同 id 内存优先）+ threading.Lock（同进程线程安全）
- **测试**: test_memory_concurrent_write.py 3 项（跨进程写不丢/同 id 内存优先/线程安全 20 条保留）+ memory 套件 22 全绿
- **待办**: 审批后推主区（随 promotion 包）

### E2. dca86eef Web 端模型全限定名透传 LLM 400
- **现象**: 高频 "[LLM 调用异常] 400"（历史曾复现）
- **方案**: routes.py /api/v1/chat 模型名归一化（provider/model 全限定名 vs 裸名）——镜像先行
- **验证**: 真实请求透传测试

## 🟡 未落地边界项（待用户确认后再列入）

### E3. 4e8ddc6c 工具结果滚动降级 → 一次性固化压缩 + 纯追加
- 状态: accepted 但代码未见完全落地（部分方案已生效: 缓存方案A/纯追加注入）
- 待确认: 是否继续推进（涉及 history.py 压缩链路）

### E4. b79b8c62 web_fetch 反爬自动降级（ttwid 校验绕过）
- 状态: accepted 未见落地
- 待确认: 优先级（web-fetch-fast skill 已部分覆盖头条）

## ⏸ 未检查/其他边界项（18 条 accepted 剩余）

- 10dc2533 模型上下文窗口自适应（本地模型）
- 33ce54e3 / edc4fa3d Skill 沉淀（figma/gh-fix-ci）——外部能力，不涉 LFL 核心
- b1f9444f 对话历史摘要注入
- f22ab8dd run_real_smoke 真实 tool-call 用例
- 7b21d0f3 / 96215428 / bfb9f215 playwright_exec 演进（多阶段）
- fcdbe2e9 技巧升格通道阶段一

> 状态说明: 2026-08-20 账目核对标记 10 条 accepted→executed（代码/配置已落地）。
> 当前 accepted 18 条 = 上表 E3/E4 + 未检查 6 条 + AI 可执行 6 条（f1e43351/dca86eef/db60d36d/d8a76517/2bd55cf3/4d62ae9d）。
